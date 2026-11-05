"""Jednorazowe CLI nad core; bez flag uruchamiany jest TUI."""

import json
import math
import os
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from portscanner.core import collect_snapshot
from portscanner.core.actions import (
    ProcessActionError,
    TerminationPending,
    prepare_kill,
    terminate_target,
)
from portscanner.core.filtering import filter_entries
from portscanner.core.ips import ExitIPError, fetch_exit_ip
from portscanner.core.model import PortEntry, Snapshot
from portscanner.core.redaction import redact_cmdline
from portscanner.presentation import COLUMNS, entry_cells, report_text, tunnel_text
from portscanner.presentation import safe_text as _safe
from portscanner.serialization import write_ports_json, write_snapshot_json

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


def _table(
    entries: list[PortEntry],
    snapshot: Snapshot,
    *,
    no_color: bool,
    columns: tuple[str, ...] = COLUMNS,
) -> None:
    """Render selected columns and connector metadata independent of port matches."""
    console = Console(no_color=no_color, markup=False, highlight=False)
    table = Table(title="Lokalne porty", show_lines=True)
    indices = [COLUMNS.index(column) for column in columns]
    for column in columns:
        table.add_column(column, overflow="fold")
    for entry in entries:
        cells = entry_cells(entry)
        table.add_row(*(Text(cells[index]) for index in indices))
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
    if any(entry.origin == "kubernetes" for entry in entries):
        console.print(
            "NodePort: konfiguracja węzła dopasowanego po lokalnym IP; "
            "nie potwierdza gniazda ani dostępności usługi."
        )
    if any(entry.proto == "udp" for entry in entries):
        console.print("UDP: związane gniazda bez weryfikacji handshake.")
    if snapshot.tunnels:
        console.print("Connectory Cloudflare Tunnel (niezależnie od filtra portów):")
        for tunnel in snapshot.tunnels:
            console.print(Text(tunnel_text(tunnel)))


def _reports(snapshot: Snapshot) -> bool:
    """Wypisz ostrzeżenia i zwróć, czy podstawowy odczyt gniazd się udał."""
    for report in snapshot.reports:
        if report.status not in ("ok", "disabled"):
            typer.echo(report_text(report), err=True)
    return any(
        report.source == "listeners"
        and (
            report.status == "ok"
            or (report.status == "partial" and report.code == "udp_peer_unknown")
        )
        for report in snapshot.reports
    )


def _kill(pid: int, *, force: bool, timeout: float) -> None:
    """Confirm the captured identity and request fresh consent after a timeout."""
    try:
        target = prepare_kill(pid)
        typer.echo(_safe(f"Proces PID {target.pid}: {target.name}"), err=True)
        # JSON zachowuje granice argumentów i ucieka znaki sterujące.
        typer.echo(
            "Argumenty: "
            + json.dumps(redact_cmdline(target.cmdline), ensure_ascii=True),
            err=True,
        )
        operation = (
            "twarde zakończenie na Windows"
            if os.name == "nt"
            else "terminate, a po timeout także kill"
            if force
            else "terminate"
        )
        if not typer.confirm(
            f"Zakończyć ten proces ({operation})?", default=False, err=True
        ):
            typer.echo("Anulowano.", err=True)
            raise typer.Exit(code=1)
        try:
            terminate_target(target, force=force, timeout=timeout)
        except TerminationPending as pending:
            typer.echo(str(pending), err=True)
            if not typer.confirm(
                "Wymusić zakończenie tego samego procesu (kill)?",
                default=False,
                err=True,
            ):
                typer.echo("Anulowano eskalację; proces może nadal działać.", err=True)
                raise typer.Exit(code=1) from pending
            pending.pending.resume(timeout=timeout)
    except ProcessActionError as error:
        typer.echo(_safe(str(error)), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Zakończono proces PID {pid}.")


@app.command()
def run(
    cli: Annotated[
        bool, typer.Option("--cli", help="Jednorazowy odczyt portów.")
    ] = False,
    gui: Annotated[
        bool, typer.Option("--gui", help="Okno desktopowe (wymaga dodatku gui).")
    ] = False,
    kube: Annotated[
        bool, typer.Option("--kube", help="Odczytaj Kubernetes i lokalne port-forward.")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Tablica portów JSON na stdout.")
    ] = False,
    json_snapshot: Annotated[
        bool,
        typer.Option(
            "--json-snapshot", help="Migawka JSON z raportami i connectorami."
        ),
    ] = False,
    columns: Annotated[
        str | None,
        typer.Option(
            "--columns",
            help="Kolumny tabeli po przecinku, np. PROTO,BIND,PORT,PID,PROC.",
        ),
    ] = None,
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
        float | None,
        typer.Option(
            "--timeout",
            help="Timeout operacji w sekundach: >0, maks. 3600.",
            show_default="3.0",
        ),
    ] = None,
) -> None:
    """PortScanner: lokalne porty, procesy, kontenery i tunele."""
    timeout_given = timeout is not None
    timeout = 3.0 if timeout is None else timeout
    if not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise typer.BadParameter(
            "Timeout musi być dodatni, skończony i nie większy niż 3600 s.",
            param_hint="--timeout",
        )
    if gui:
        if any(
            (
                cli,
                json_output,
                json_snapshot,
                columns is not None,
                query is not None,
                kill is not None,
                force,
                no_color,
                no_docker,
                no_tunnels,
                no_metrics,
                exit_ip,
                timeout_given,
            )
        ):
            raise typer.BadParameter("--gui nie łączy się z opcjami CLI.")
        from portscanner.gui import GuiLaunchError, launch

        try:
            launch(kube=kube)
        except GuiLaunchError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from error
        return
    if not cli:
        if any(
            (
                json_output,
                json_snapshot,
                columns is not None,
                query is not None,
                kill is not None,
                force,
                no_color,
                no_docker,
                no_tunnels,
                no_metrics,
                exit_ip,
                timeout_given,
            )
        ):
            raise typer.BadParameter("Te opcje wymagają --cli.")
        from portscanner.tui import PortScannerApp

        PortScannerApp(kube=kube).run()
        return
    if force and kill is None:
        raise typer.BadParameter("--force wymaga --kill.")
    if kill is not None:
        if any(
            (
                json_output,
                json_snapshot,
                columns is not None,
                query is not None,
                exit_ip,
                no_docker,
                no_tunnels,
                no_metrics,
                kube,
            )
        ):
            raise typer.BadParameter("--kill nie łączy się z opcjami odczytu portów.")
        _kill(kill, force=force, timeout=timeout)
        return
    if json_output and json_snapshot:
        raise typer.BadParameter("Wybierz --json albo --json-snapshot.")
    if (json_output or json_snapshot) and (exit_ip or columns is not None):
        raise typer.BadParameter("--exit-ip i --columns nie łączą się z trybami JSON.")
    selected_columns = COLUMNS
    if columns is not None:
        selected_columns = tuple(
            column.strip().upper() for column in columns.split(",")
        )
        if any(column not in COLUMNS for column in selected_columns) or len(
            set(selected_columns)
        ) != len(selected_columns):
            raise typer.BadParameter(
                "Podaj unikalne kolumny z listy: " + ", ".join(COLUMNS),
                param_hint="--columns",
            )
    try:
        filter_entries((), query)  # Walidacja przed odczytem systemu lub sieci.
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--filter") from error
    snapshot = collect_snapshot(
        docker=not no_docker,
        tunnels=not no_tunnels,
        metrics=not no_metrics,
        kube=kube,
        timeout=timeout,
    )
    entries = filter_entries(snapshot.ports, query)
    if json_output:
        write_ports_json(entries, typer.get_text_stream("stdout"))
    elif json_snapshot:
        write_snapshot_json(snapshot, entries, typer.get_text_stream("stdout"))
    else:
        _table(entries, snapshot, no_color=no_color, columns=selected_columns)
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
