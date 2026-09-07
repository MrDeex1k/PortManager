"""Podstawowy model lokalnego gniazda; wzbogacanie danych w kolejnych fazach."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class SourceReport:
    """Stan źródła; brak danych odróżniony od nieudanego odczytu."""

    source: str
    status: Literal["ok", "partial", "unavailable", "error", "disabled"]
    message: str | None = None


@dataclass(frozen=True, slots=True)
class Collection[T]:
    items: tuple[T, ...]
    report: SourceReport


@dataclass(frozen=True, slots=True)
class DockerPort:
    container_id: str
    container_name: str
    host_bind: str
    host_port: int
    container_port: int
    proto: Literal["tcp", "udp"]
    compose_project: str | None = None
    compose_service: str | None = None


@dataclass(frozen=True, slots=True)
class TunnelRoute:
    """Reguła konfiguracji; nie potwierdza publicznej dostępności hostname."""

    pid: int
    hostname: str | None
    host: str
    port: int
    path: str | None = None


@dataclass(frozen=True, slots=True)
class TunnelInfo:
    pid: int
    routes: tuple[TunnelRoute, ...] = ()
    config_status: Literal["explicit", "inferred", "remote", "unavailable", "error"] = (
        "unavailable"
    )
    metrics_status: Literal["ok", "unavailable", "error", "disabled"] = "unavailable"
    connections: int | None = None


@dataclass(frozen=True, slots=True)
class ServiceTag:
    name: Literal["k8s", "k3s", "microk8s"]
    evidence: Literal["process", "port"]


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
    docker: tuple[DockerPort, ...] = ()
    tunnels: tuple[TunnelRoute, ...] = ()
    tags: tuple[ServiceTag, ...] = ()
    origin: Literal["socket", "docker"] = "socket"


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


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Wspólne API core dla przyszłych interfejsów; bez automatycznego exit IP."""

    ports: tuple[PortEntry, ...]
    local_ips: tuple[LocalIP, ...]
    docker: tuple[DockerPort, ...]
    tunnels: tuple[TunnelInfo, ...]
    reports: tuple[SourceReport, ...]
