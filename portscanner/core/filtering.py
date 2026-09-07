"""Filtry portów współdzielone przez CLI i przyszły TUI."""

from collections.abc import Iterable

from portscanner.core.model import PortEntry


def filter_entries(entries: Iterable[PortEntry], query: str | None) -> list[PortEntry]:
    """`:PORT` i `pid:PID` są dokładne; reszta to podciąg bez wielkości liter."""
    if query is None:
        return list(entries)
    query = query.strip().casefold()
    if not query:
        raise ValueError("Filtr nie może być pusty.")
    if query.startswith(":") and not query.startswith("::"):
        port = _number(query[1:], "port", 1, 65535)
        return [entry for entry in entries if entry.port == port]
    if query.startswith("pid:"):
        pid = _number(query[4:], "PID", 0, None)
        return [entry for entry in entries if entry.pid == pid]
    return [entry for entry in entries if query in _search_text(entry)]


def _number(value: str, label: str, minimum: int, maximum: int | None) -> int:
    if not value.isascii() or not value.isdigit():
        raise ValueError(f"Filtr {label} wymaga liczby całkowitej.")
    number = int(value)
    if number < minimum or (maximum is not None and number > maximum):
        raise ValueError(f"Filtr {label}: liczba poza zakresem.")
    return number


def _search_text(entry: PortEntry) -> str:
    fields = [entry.proto, entry.bind, str(entry.port), entry.origin]
    if entry.pid is not None:
        fields.append(str(entry.pid))
    if entry.process:
        fields.extend([entry.process.name or "", *(entry.process.cmdline or ())])
    for mapping in entry.docker:
        fields.extend(
            [
                mapping.container_id,
                mapping.container_name,
                mapping.compose_project or "",
                mapping.compose_service or "",
            ]
        )
    fields.extend(route.hostname or "" for route in entry.tunnels)
    fields.extend(tag.name for tag in entry.tags)
    return " ".join(fields).casefold()
