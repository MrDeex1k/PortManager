"""Wspólne komórki CLI/TUI; dane z systemu nigdy nie stają się markupem."""

import unicodedata

from portscanner.core.model import PortEntry, SourceReport, TunnelInfo

COLUMNS = (
    "PROTO",
    "BIND",
    "PORT",
    "PID",
    "PROC",
    "DOCKER",
    "TUNNEL",
    "TAG",
    "KUBERNETES",
    "ŹRÓDŁO",
)


def safe_text(text: str) -> str:
    return "".join(
        char if unicodedata.category(char) not in ("Cc", "Cf") else "?" for char in text
    )


def report_text(report: SourceReport) -> str:
    """Expose safe reason codes consistently in both terminal interfaces."""
    code = f" [{report.code}]" if report.code else ""
    message = report.message or (
        "Niepełne lub niedostępne dane źródła."
        if report.status not in ("ok", "disabled")
        else ""
    )
    return safe_text(f"{report.source}: {report.status}{code} — {message}")


def tunnel_text(tunnel: TunnelInfo) -> str:
    """Describe every connector, including remote configs and unknown metrics."""
    config_code = f" [{tunnel.config_code}]" if tunnel.config_code else ""
    metrics_code = f" [{tunnel.metrics_code}]" if tunnel.metrics_code else ""
    connections = "?" if tunnel.connections is None else str(tunnel.connections)
    return safe_text(
        f"PID {tunnel.pid}: config={tunnel.config_status}{config_code}; "
        f"metryki={tunnel.metrics_status}{metrics_code}; "
        f"połączenia={connections}; reguły={len(tunnel.routes)}"
    )


def entry_cells(entry: PortEntry) -> tuple[str, ...]:
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
    return tuple(
        safe_text(value)
        for value in (
            entry.proto,
            entry.bind,
            str(entry.port),
            str(entry.pid) if entry.pid is not None else "?",
            name,
            docker or "—",
            tunnels or "—",
            tags or "—",
            "; ".join(
                f"{m.namespace or '?'}/{m.resource}:{m.remote_port} [{m.kind}]"
                + (f" node={m.node}" if m.node else "")
                + (f" context={m.context}" if m.context else "")
                for m in entry.kubernetes
            )
            or "—",
            entry.origin,
        )
    )
