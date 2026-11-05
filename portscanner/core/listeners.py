"""Odczyt lokalnych gniazd, bez prób połączeń i zależności od UI."""

import socket
import sys
from dataclasses import replace
from ipaddress import ip_address
from typing import Literal

import psutil

from portscanner.core.model import Collection, PortEntry, SourceReport


class ListenerScanError(RuntimeError):
    """System nie pozwolił odczytać migawki gniazd."""


class ListenerAccessDenied(ListenerScanError):
    """Odczyt całej listy został odrzucony z powodu uprawnień."""


def collect_listeners(*, group_dual_stack: bool = True) -> list[PortEntry]:
    """Zwróć uporządkowaną migawkę TCP LISTEN i UDP bez zdalnego adresu.

    UDP oznacza związane gniazdo bez widocznego peera, nie potwierdzoną usługę.
    Windows nie udostępnia peera UDP: udp_peer_status jest wtedy unknown.
    Numery portów nie są filtrem: także wysoki port może należeć do serwera.
    Brak dostępu do całej listy zgłasza ListenerAccessDenied zamiast pustej
    listy. Inne błędy systemowe zgłaszają ListenerScanError. Na niektórych
    systemach psutil może pominąć niedostępne gniazda bez błędu; wynik nie
    gwarantuje kompletności. Nie podnosimy uprawnień automatycznie.

    Grupowanie to prezentacja par wildcard tego samego znanego PID, protokołu
    i portu jako bind='*', a nie dowód ustawienia IPV6_V6ONLY. Można je wyłączyć,
    aby zachować osobne adresy IPv4/IPv6. Nieznanych PID nie łączymy w pary.
    """
    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError) as exc:
        raise ListenerAccessDenied(
            "Brak uprawnień do odczytu lokalnych gniazd. "
            "Na macOS odczyt systemowy może wymagać uprawnień root."
        ) from exc
    except (psutil.Error, OSError, RuntimeError) as exc:
        raise ListenerScanError("Nie udało się odczytać lokalnych gniazd.") from exc

    return _entries(connections, group_dual_stack=group_dual_stack)


def _entries(connections, *, group_dual_stack: bool = True) -> list[PortEntry]:
    """Normalize TCP listeners and UDP bindings, preserving unknown Windows peers."""
    entries: set[PortEntry] = set()
    for connection in connections:
        if connection.family not in (socket.AF_INET, socket.AF_INET6):
            continue
        if not connection.laddr or connection.laddr.port == 0:
            continue

        proto: Literal["tcp", "udp"]
        if connection.type == socket.SOCK_STREAM:
            if connection.status != psutil.CONN_LISTEN:
                continue
            proto = "tcp"
        elif connection.type == socket.SOCK_DGRAM:
            if connection.raddr:
                continue
            proto = "udp"
        else:
            continue

        try:
            bind = str(ip_address(connection.laddr.ip))
        except ValueError:
            continue
        entries.add(
            PortEntry(
                proto=proto,
                bind=bind,
                port=connection.laddr.port,
                pid=(
                    None
                    if sys.platform == "win32" and connection.pid == 0
                    else connection.pid
                ),
                udp_peer_status=("unknown" if sys.platform == "win32" else "absent")
                if proto == "udp"
                else "not_applicable",
            )
        )

    if group_dual_stack:
        entries = _group_wildcards(entries)
    return sorted(
        entries,
        key=lambda entry: (
            entry.port,
            entry.proto,
            entry.bind,
            entry.pid if entry.pid is not None else -1,
        ),
    )


def _group_wildcards(entries: set[PortEntry]) -> set[PortEntry]:
    grouped = entries.copy()
    for entry in entries:
        if entry.bind != "0.0.0.0" or entry.pid is None:
            continue
        ipv6 = replace(entry, bind="::")
        if ipv6 in entries:
            grouped.remove(entry)
            grouped.remove(ipv6)
            grouped.add(replace(entry, bind="*"))
    return grouped


def collect_accessible_listeners() -> Collection[PortEntry]:
    """Best-effort macOS scan after system-wide access denial, never elevate."""
    from types import SimpleNamespace

    connections = []
    try:
        for process in psutil.process_iter():
            try:
                for connection in process.net_connections(kind="inet"):
                    connections.append(
                        SimpleNamespace(
                            family=connection.family,
                            type=connection.type,
                            laddr=connection.laddr,
                            raddr=connection.raddr,
                            status=connection.status,
                            pid=process.pid,
                        )
                    )
            except (psutil.Error, OSError, RuntimeError):
                continue
    except (psutil.Error, OSError, RuntimeError):
        pass
    return Collection(
        tuple(_entries(connections)),
        SourceReport(
            "listeners",
            "partial",
            "Odmowa odczytu systemowego; pokazano tylko gniazda dostępnych procesów.",
        ),
    )
