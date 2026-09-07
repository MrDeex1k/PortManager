"""Wzbogacanie portów o procesy, bez utrwalania cache między migawkami."""

from collections.abc import Iterable
from dataclasses import replace

import psutil

from portscanner.core.model import PortEntry, ProcessInfo
from portscanner.core.redaction import redact_cmdline


def read_process(pid: int | None) -> ProcessInfo:
    """Odczytaj nazwę i argumenty, zachowując dostępne pola przy AccessDenied.

    Nieznany PID nie uruchamia odczytu psutil.Process(None), który oznaczałby
    własny proces. Zakończenie lub wykryte ponowne użycie PID podczas odczytu
    usuwa częściowe szczegóły i zwraca status gone. Odczyt portów i procesów
    nie jest atomowy; ta migawka nie nadaje się do autoryzacji kończenia procesu.
    """
    if pid is None:
        return ProcessInfo(pid=None, status="unknown")
    if isinstance(pid, bool) or pid < 0:
        raise ValueError("PID musi być nieujemną liczbą całkowitą albo None.")

    name: str | None = None
    cmdline: tuple[str, ...] | None = None
    denied = False
    try:
        process = psutil.Process(pid)
        try:
            name = process.name()
        except (psutil.AccessDenied, PermissionError):
            denied = True
        try:
            cmdline = tuple(process.cmdline())
        except (psutil.AccessDenied, PermissionError):
            denied = True
        if not process.is_running():
            return ProcessInfo(pid=pid, status="gone")
    except psutil.NoSuchProcess:
        # ZombieProcess jest podklasą NoSuchProcess.
        return ProcessInfo(pid=pid, status="gone")
    except (psutil.AccessDenied, PermissionError):
        denied = True
    except (psutil.Error, OSError):
        return ProcessInfo(pid=pid, status="error")

    return ProcessInfo(
        pid=pid,
        status="access_denied" if denied else "ok",
        name=name,
        cmdline=None if cmdline is None else redact_cmdline(cmdline),
    )


def enrich_processes(entries: Iterable[PortEntry]) -> list[PortEntry]:
    """Zwróć nowe wpisy, odczytując każdy PID najwyżej raz w tej migawce."""
    processes: dict[int | None, ProcessInfo] = {}
    result: list[PortEntry] = []
    for entry in entries:
        if entry.pid not in processes:
            processes[entry.pid] = read_process(entry.pid)
        result.append(replace(entry, process=processes[entry.pid]))
    return result
