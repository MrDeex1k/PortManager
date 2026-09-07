"""Odczyt lokalnych gniazd, bez prób połączeń i zależności od UI."""

import socket
from dataclasses import replace
from ipaddress import ip_address
from typing import Literal

import psutil

from portscanner.core.model import PortEntry


class ListenerScanError(RuntimeError):
    """System nie pozwolił odczytać migawki gniazd."""


class ListenerAccessDenied(ListenerScanError):
    """Odczyt całej listy został odrzucony z powodu uprawnień."""


def collect_listeners(*, group_dual_stack: bool = True) -> list[PortEntry]:
    """Zwróć uporządkowaną migawkę TCP LISTEN i UDP bez zdalnego adresu.

    UDP oznacza związane gniazdo bez peera, nie potwierdzoną usługę serwerową.
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
    except (psutil.Error, OSError) as exc:
        raise ListenerScanError("Nie udało się odczytać lokalnych gniazd.") from exc

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
                pid=connection.pid,
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
