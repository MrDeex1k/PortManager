"""Jednorazowe CLI nad core; bez flag nadal wybierany jest przyszły TUI."""

import json
import math
import unicodedata
from dataclasses import asdict
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from portscanner.core import collect_snapshot
from portscanner.core.actions import ProcessActionError, prepare_kill, terminate_target
from portscanner.core.filtering import filter_entries
from portscanner.core.ips import ExitIPError, fetch_exit_ip
from portscanner.core.model import PortEntry, Snapshot

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


def _safe(text: str) -> str:
    # Dane procesów/configów nie mogą sterować terminalem ani używać Rich markup.
    return "".join(
        char if unicodedata.category(char) not in ("Cc", "Cf") else "?" for char in text
    )


def _table(entries: list[PortEntry], snapshot: Snapshot, *, no_color: bool) -> None:
    console = Console(no_color=no_color, markup=False, highlight=False)
    table = Table(title="Lokalne porty", show_lines=True)
    for column in (
        "PROTO",
        "BIND",
        "PORT",
        "PID",
        "PROC",
        "DOCKER",
        "TUNNEL",
        "TAG",
        "ŹRÓDŁO",
    ):
        table.add_column(column, overflow="fold")
    for entry in entries:
        process = entry.process
        name = process.name if process and process.name else "?"
        if process and process.status != "ok":
            name += f" ({process.status})"
        docker = "; ".join(
            f"{m.container_name}: {m.host_port} → {m.container_port}/{m.proto}"
            + (
                f" ({m.compose_project}/{m.compose_service or '?'})"
                if m.compose_project
                else ""
            )
            for m in entry.docker
        )
        tunnels = "; ".join(
            f"{r.hostname or '(hostname nieznany)'}"
            f"{(' path=' + r.path) if r.path else ''} [config]"
            for r in entry.tunnels
        )
        tags = ", ".join(f"{tag.name} ({tag.evidence})" for tag in entry.tags)
        table.add_row(
            *(
                Text(_safe(value))
                for value in (
                    entry.proto,
                    entry.bind,
                    str(entry.port),
                    str(entry.pid) if entry.pid is not None else "?",
                    name,
                    docker or "—",
                    tunnels or "—",
                    tags or "—",
                    entry.origin,
                )
            )
        )
    console.print(table)
    if not entries:
        console.print("Brak pasujących wpisów w dostępnych danych.")
    if snapshot.local_ips:
        console.print(
            Text(
                "IP lokalne: "
                + "; ".join(
                    _safe(f"{ip.interface}: {ip.address}") for ip in snapshot.local_ips
                )
            )
        )
    if any(entry.origin == "docker" for entry in entries):
        console.print(
            "Źródło docker oznacza publikację bez potwierdzonego gniazda hosta."
        )
    if any(entry.proto == "udp" for entry in entries):
        console.print("UDP: związane gniazda bez weryfikacji handshake.")


def _reports(snapshot: Snapshot) -> bool:
    """Wypisz ostrzeżenia i zwróć, czy podstawowy odczyt gniazd się udał."""
    for report in snapshot.reports:
        if report.status not in ("ok", "disabled"):
            message = report.message or "Niepełne lub niedostępne dane źródła."
            typer.echo(_safe(f"{report.source}: {report.status} — {message}"), err=True)
    return any(
        report.source == "listeners" and report.status == "ok"
        for report in snapshot.reports
    )


def _kill(pid: int, *, force: bool, timeout: float) -> None:
    try:
        target = prepare_kill(pid)
        typer.echo(_safe(f"Proces PID {target.pid}: {target.name}"), err=True)
        # JSON zachowuje granice argumentów i ucieka znaki sterujące.
        typer.echo(
            "Argumenty: " + json.dumps(target.cmdline, ensure_ascii=True), err=True
        )
        operation = "terminate, a po timeout także kill" if force else "terminate"
        if not typer.confirm(
            f"Zakończyć ten proces ({operation})?", default=False, err=True
        ):
            typer.echo("Anulowano.", err=True)
            raise typer.Exit(code=1)
        terminate_target(target, force=force, timeout=timeout)
    except ProcessActionError as error:
        typer.echo(_safe(str(error)), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Zakończono proces PID {pid}.")


@app.command()
def run(
    cli: Annotated[
        bool, typer.Option("--cli", help="Jednorazowy odczyt portów.")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Tablica portów JSON na stdout.")
    ] = False,
    query: Annotated[
        str | None, typer.Option("--filter", help="Filtr :PORT, pid:PID lub tekst.")
    ] = None,
    kill: Annotated[
        int | None,
        typer.Option(
            "--kill", min=1, help="Zakończ własny proces z portem, po potwierdzeniu."
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Z --kill: pozwól na kill po timeout; nadal wymaga potwierdzenia.",
        ),
    ] = False,
    no_color: Annotated[
        bool, typer.Option("--no-color", help="Wyłącz kolory tabeli.")
    ] = False,
    no_docker: Annotated[
        bool, typer.Option("--no-docker", help="Pomiń Docker CLI.")
    ] = False,
    no_tunnels: Annotated[
        bool, typer.Option("--no-tunnels", help="Pomiń konfiguracje i metryki tuneli.")
    ] = False,
    no_metrics: Annotated[
        bool, typer.Option("--no-metrics", help="Nie odpytuj metryk HTTP loopback.")
    ] = False,
    exit_ip: Annotated[
        bool,
        typer.Option(
            "--exit-ip", help="Jawnie odpytaj ipify przez HTTPS (tylko tabela)."
        ),
    ] = False,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Timeout pojedynczej operacji w sekundach."),
    ] = 3.0,
) -> None:
    """PortScanner: lokalne porty, procesy, kontenery i tunele."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise typer.BadParameter(
            "Timeout musi być dodatni i skończony.", param_hint="--timeout"
        )
    if not cli:
        if any(
            (
                json_output,
                query is not None,
                kill is not None,
                force,
                no_color,
                no_docker,
                no_tunnels,
                no_metrics,
                exit_ip,
                timeout != 3.0,
            )
        ):
            raise typer.BadParameter("Te opcje wymagają --cli.")
        typer.echo(
            "Tryb domyślny to TUI, dostępny od Fazy 5. Użyj --cli lub --help.", err=True
        )
        raise typer.Exit(code=1)
    if force and kill is None:
        raise typer.BadParameter("--force wymaga --kill.")
    if kill is not None:
        if any(
            (json_output, query is not None, exit_ip, no_docker, no_tunnels, no_metrics)
        ):
            raise typer.BadParameter("--kill nie łączy się z opcjami odczytu portów.")
        _kill(kill, force=force, timeout=timeout)
        return
    if json_output and exit_ip:
        raise typer.BadParameter(
            "--exit-ip nie łączy się z --json (kontrakt to lista portów)."
        )
    try:
        filter_entries((), query)  # Walidacja przed odczytem systemu lub sieci.
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--filter") from error
    snapshot = collect_snapshot(
        docker=not no_docker,
        tunnels=not no_tunnels,
        metrics=not no_metrics,
        timeout=timeout,
    )
    entries = filter_entries(snapshot.ports, query)
    if json_output:
        typer.echo(
            json.dumps(
                [asdict(entry) for entry in entries], ensure_ascii=True, indent=2
            )
        )
    else:
        _table(entries, snapshot, no_color=no_color)
    success = _reports(snapshot)
    if exit_ip:
        try:
            result = fetch_exit_ip(timeout=timeout)
            typer.echo(f"{result.label}: {result.address}")
        except ExitIPError as error:
            typer.echo(str(error), err=True)
            success = False
    if not success:
        raise typer.Exit(code=1)


def main() -> None:
    """Punkt wejścia instalowanego pakietu."""
    app()
