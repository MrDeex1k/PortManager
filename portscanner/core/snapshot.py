"""Łączenie źródeł bez ukrywania błędów i bez automatycznego exit IP."""

import math
from dataclasses import replace
from ipaddress import ip_address

from portscanner.core.cloudflared import collect_tunnels
from portscanner.core.docker import collect_docker
from portscanner.core.ips import LocalIPError, collect_local_ips
from portscanner.core.k8s import tag_entry
from portscanner.core.listeners import ListenerScanError, collect_listeners
from portscanner.core.model import (
    Collection,
    DockerPort,
    LocalIP,
    PortEntry,
    Snapshot,
    SourceReport,
    TunnelInfo,
    TunnelRoute,
)
from portscanner.core.procs import enrich_processes


def _docker_matches(entry: PortEntry, mapping: DockerPort) -> bool:
    return (
        entry.proto == mapping.proto
        and entry.port == mapping.host_port
        and (
            entry.bind == mapping.host_bind
            or (entry.bind == "*" and mapping.host_bind in ("0.0.0.0", "::"))
        )
    )


def _route_matches(
    entry: PortEntry, route: TunnelRoute, local_ips: tuple[LocalIP, ...]
) -> bool:
    if entry.proto != "tcp" or entry.port != route.port:
        return False
    if route.host == "localhost":
        return (
            entry.bind in ("*", "0.0.0.0", "::") or ip_address(entry.bind).is_loopback
        )
    try:
        address = ip_address(route.host)
    except ValueError:
        return False  # Nazwy origin nie są rozwiązywane przez DNS.
    if str(address) == entry.bind:
        return True
    if not address.is_loopback and str(address) not in {ip.address for ip in local_ips}:
        return False
    return entry.bind == "*" or entry.bind == (
        "0.0.0.0" if address.version == 4 else "::"
    )


def merge_sources(
    entries: list[PortEntry],
    mappings: tuple[DockerPort, ...],
    tunnels: tuple[TunnelInfo, ...],
    local_ips: tuple[LocalIP, ...] = (),
) -> tuple[PortEntry, ...]:
    """Dopasowanie jest informacyjne; mapowania bez gniazda mają origin=docker.

    Nie przypisujemy PID kontenera do hosta. Dla Dockera wymagamy zgodnego
    bindu (lub zgrupowanej pary wildcard), protokołu i portu.
    """
    enriched = []
    remaining = set(mappings)
    for entry in entries:
        matched = tuple(
            mapping for mapping in mappings if _docker_matches(entry, mapping)
        )
        remaining.difference_update(matched)
        enriched.append(replace(entry, docker=matched))
    synthetic: dict[tuple[str, str, int], list[DockerPort]] = {}
    for mapping in mappings:
        if mapping in remaining:
            synthetic.setdefault(
                (mapping.proto, mapping.host_bind, mapping.host_port), []
            ).append(mapping)
    for group in synthetic.values():
        first = group[0]
        enriched.append(
            PortEntry(
                first.proto,
                first.host_bind,
                first.host_port,
                docker=tuple(group),
                origin="docker",
            )
        )
    routes = tuple(route for tunnel in tunnels for route in tunnel.routes)
    return tuple(
        sorted(
            (
                tag_entry(
                    replace(
                        entry,
                        tunnels=tuple(
                            route
                            for route in routes
                            if _route_matches(entry, route, local_ips)
                        ),
                    )
                )
                for entry in enriched
            ),
            key=lambda entry: (
                entry.port,
                entry.proto,
                entry.bind,
                entry.pid if entry.pid is not None else -1,
                entry.origin,
            ),
        )
    )


def collect_snapshot(
    *,
    docker: bool = True,
    tunnels: bool = True,
    metrics: bool = True,
    timeout: float = 3.0,
) -> Snapshot:
    """Odczytaj lokalne źródła; błędy znajdują się w reports, nie znikają.

    Włączenie tuneli zezwala na odczyt konfiguracji wykrytych procesów;
    metrics wykonuje HTTP tylko na loopback przypisanym do cloudflared.
    Exit IP ma nadal osobne, jawne API. Brak odczytu gniazd nie blokuje
    informacji z Dockera, ale raport listeners informuje o niepełnej migawce.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatni i skończony")
    reports = []
    try:
        entries = enrich_processes(collect_listeners())
        reports.append(SourceReport("listeners", "ok"))
        incomplete = any(
            entry.process is not None and entry.process.status != "ok"
            for entry in entries
        )
        reports.append(SourceReport("processes", "partial" if incomplete else "ok"))
    except ListenerScanError:
        entries = []
        reports.extend(
            (
                SourceReport("listeners", "error", "Odczyt gniazd niedostępny."),
                SourceReport("processes", "unavailable"),
            )
        )
    try:
        local_ips = tuple(collect_local_ips())
        reports.append(SourceReport("local_ips", "ok"))
    except LocalIPError:
        local_ips = ()
        reports.append(
            SourceReport("local_ips", "error", "Odczyt interfejsów niedostępny.")
        )
    docker_result: Collection[DockerPort] = (
        collect_docker(timeout=timeout)
        if docker
        else Collection((), SourceReport("docker", "disabled"))
    )
    tunnel_result: Collection[TunnelInfo] = (
        collect_tunnels(metrics=metrics, timeout=timeout)
        if tunnels
        else Collection((), SourceReport("tunnels", "disabled"))
    )
    reports.extend((docker_result.report, tunnel_result.report))
    return Snapshot(
        ports=merge_sources(
            entries, docker_result.items, tunnel_result.items, local_ips
        ),
        local_ips=local_ips,
        docker=docker_result.items,
        tunnels=tunnel_result.items,
        reports=tuple(reports),
    )
