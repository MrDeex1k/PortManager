"""Podstawowy model lokalnego gniazda; wzbogacanie danych w kolejnych fazach."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PortEntry:
    """Migawka gniazda; brak PID oznacza nieznanego właściciela.

    Bind przechowuje sam adres (IPv4 lub IPv6), port jest osobnym polem.
    Model nie wykonuje odczytów systemowych ani nie zależy od UI.
    """

    proto: Literal["tcp", "udp"]
    bind: str
    port: int
    pid: int | None = None
