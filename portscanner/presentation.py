"""Wspólne komórki CLI/TUI; dane z systemu nigdy nie stają się markupem."""

import unicodedata

from portscanner.core.model import PortEntry

COLUMNS = ("PROTO", "BIND", "PORT", "PID", "PROC", "DOCKER", "TUNNEL", "TAG", "ŹRÓDŁO")


def safe_text(text: str) -> str:
    return "".join(
        char if unicodedata.category(char) not in ("Cc", "Cf") else "?" for char in text
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
            entry.origin,
        )
    )
