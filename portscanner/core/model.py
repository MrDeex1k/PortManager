"""Podstawowy model lokalnego gniazda; wzbogacanie danych w kolejnych fazach."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    """Migawka procesu; status opisuje odczyt, nie stan procesu w systemie.

    None w name/cmdline oznacza niedostępne dane, pusty tuple to odczytana
    pusta lista argumentów. Dane są informacyjne, nie upoważniają do kill PID.
    """

    pid: int | None
    status: Literal["ok", "unknown", "access_denied", "gone", "error"]
    name: str | None = None
    cmdline: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class PortEntry:
    """Migawka gniazda; brak PID oznacza nieznanego właściciela.

    Bind przechowuje sam adres (IPv4 lub IPv6), port jest osobnym polem.
    Wartość '*' oznacza zgrupowaną parę wildcard IPv4/IPv6 tego samego PID.
    Model nie wykonuje odczytów systemowych ani nie zależy od UI.
    """

    proto: Literal["tcp", "udp"]
    bind: str
    port: int
    pid: int | None = None
    process: ProcessInfo | None = None


@dataclass(frozen=True, slots=True)
class LocalIP:
    """Adres przypisany do interfejsu; nie oznacza trasy domyślnej."""

    interface: str
    address: str
    family: Literal["ipv4", "ipv6"]


@dataclass(frozen=True, slots=True)
class ExitIP:
    """Adres widziany przez zewnętrzną usługę po użytej trasie HTTP(S)."""

    address: str
    family: Literal["ipv4", "ipv6"]
    source: str
    label: str = "exit IP (widziane z internetu)"
