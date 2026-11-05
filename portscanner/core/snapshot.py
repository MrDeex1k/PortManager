"""Łączenie źródeł bez ukrywania błędów i bez automatycznego exit IP."""

import math
import sys
from collections import defaultdict
from dataclasses import replace
from ipaddress import ip_address

from portscanner.core.cloudflared import collect_tunnels
from portscanner.core.docker import collect_docker
from portscanner.core.ips import LocalIPError, collect_local_ips
from portscanner.core.k8s import tag_entry
from portscanner.core.kube import collect_kube
from portscanner.core.kube_cache import KubeDiscovery
from portscanner.core.listeners import (
    ListenerAccessDenied,
    ListenerScanError,
    collect_accessible_listeners,
    collect_listeners,
)
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
    entry: PortEntry, route: TunnelRoute, local_addresses: set[str]
) -> bool:
    """Match TCP origins to local binds without resolving hostnames through DNS."""
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
    if not address.is_loopback and str(address) not in local_addresses:
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
    return attach_tunnels(_merge_docker(entries, mappings), tunnels, local_ips)


def _merge_docker(
    entries: list[PortEntry],
    mappings: tuple[DockerPort, ...],
) -> tuple[PortEntry, ...]:
    """Index publications by protocol/port; keep unmatched synthetic rows."""
    enriched = []
    by_port: dict[tuple[str, int], list[DockerPort]] = defaultdict(list)
    for mapping in mappings:
        by_port[mapping.proto, mapping.host_port].append(mapping)
    remaining = set(mappings)
    for entry in entries:
        matched = tuple(
            mapping
            for mapping in by_port[entry.proto, entry.port]
            if _docker_matches(entry, mapping)
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
    return tuple(enriched)


def attach_tunnels(
    entries: tuple[PortEntry, ...],
    tunnels: tuple[TunnelInfo, ...],
    local_ips: tuple[LocalIP, ...],
) -> tuple[PortEntry, ...]:
    """Attach relations after all synthetic rows have been created, without DNS."""
    routes_by_port: dict[int, list[TunnelRoute]] = defaultdict(list)
    for tunnel in tunnels:
        for route in tunnel.routes:
            routes_by_port[route.port].append(route)
    local_addresses = {ip.address for ip in local_ips}
    return tuple(
        sorted(
            (
                tag_entry(
                    replace(
                        entry,
                        tunnels=tuple(
                            route
                            for route in routes_by_port[entry.port]
                            if _route_matches(entry, route, local_addresses)
                        ),
                    )
                )
                for entry in entries
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
    kube: bool = False,
    kube_discovery: KubeDiscovery | None = None,
    timeout: float = 3.0,
    accessible_fallback: bool = True,
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
        try:
            listeners = collect_listeners()
            report = SourceReport("listeners", "ok")
        except ListenerAccessDenied:
            if sys.platform != "darwin" or not accessible_fallback:
                raise
            fallback = collect_accessible_listeners()
            listeners, report = list(fallback.items), fallback.report
        if report.status == "ok" and any(
            entry.udp_peer_status == "unknown" for entry in listeners
        ):
            report = replace(
                report,
                status="partial",
                code="udp_peer_unknown",
                message=(
                    "Windows nie udostępnia informacji o peerze UDP; "
                    "lista obejmuje również endpointy klientów."
                ),
            )
        entries = enrich_processes(listeners)
        reports.append(report)
        incomplete = any(
            entry.process is not None and entry.process.status != "ok"
            for entry in entries
        )
        reports.append(SourceReport("processes", "partial" if incomplete else "ok"))
    except ListenerScanError as error:
        entries = []
        reports.extend(
            (
                SourceReport(
                    "listeners",
                    "unavailable"
                    if isinstance(error, ListenerAccessDenied)
                    else "error",
                    str(error),
                ),
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
    ports = _merge_docker(entries, docker_result.items)
    if kube:
        result = (
            collect_kube(ports, local_ips, timeout=timeout)
            if kube_discovery is None
            else kube_discovery.collect(ports, local_ips, timeout=timeout)
        )
        ports = result.items
        reports.append(result.report)
    ports = attach_tunnels(ports, tunnel_result.items, local_ips)
    return Snapshot(
        ports=ports,
        local_ips=local_ips,
        docker=docker_result.items,
        tunnels=tunnel_result.items,
        reports=tuple(reports),
    )
