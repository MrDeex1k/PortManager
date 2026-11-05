"""Wspólna migawka zachowuje pochodzenie danych i błędy źródeł."""

import json
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from portscanner.core import snapshot as snap
from portscanner.core.ips import LocalIPError
from portscanner.core.k8s import tag_entry
from portscanner.core.listeners import ListenerAccessDenied
from portscanner.core.model import (
    Collection,
    DockerPort,
    LocalIP,
    PortEntry,
    ProcessInfo,
    SourceReport,
    TunnelInfo,
    TunnelRoute,
)


def mapping(bind: str = "0.0.0.0", port: int = 8080) -> DockerPort:
    return DockerPort("a", "web", bind, port, 80, "tcp")


def test_docker_pair_attaches_to_grouped_socket_without_duplicate() -> None:
    docker = (mapping(), mapping("::"))
    result = snap.merge_sources([PortEntry("tcp", "*", 8080, 42)], docker, ())
    assert len(result) == 1
    assert result[0].docker == docker and result[0].pid == 42
    assert result[0].origin == "socket"


def test_docker_does_not_match_protocol_or_other_interface() -> None:
    entries = [
        PortEntry("udp", "0.0.0.0", 8080, 1),
        PortEntry("tcp", "127.0.0.1", 8080, 2),
    ]
    result = snap.merge_sources(entries, (mapping(),), ())
    assert len(result) == 3
    synthetic = [r for r in result if r.origin == "docker"]
    assert len(synthetic) == 1 and synthetic[0].pid is None
    assert all(not r.docker for r in result if r.origin == "socket")


def test_multiple_containers_share_synthetic_row_without_losing_identity() -> None:
    one = mapping()
    two = DockerPort("b", "other", "0.0.0.0", 8080, 81, "tcp")
    result = snap.merge_sources([], (one, two), ())
    assert len(result) == 1 and result[0].docker == (one, two)


def test_tunnel_matching_respects_local_bind_protocol_and_all_rules() -> None:
    routes = (
        TunnelRoute(42, "app.example.com", "localhost", 8080),
        TunnelRoute(42, "remote.example.com", "192.0.2.10", 8080),
        TunnelRoute(42, "named.example.com", "some-server", 8080),
    )
    tunnel = TunnelInfo(42, routes, "explicit")
    entries = [
        PortEntry("tcp", "0.0.0.0", 8080),
        PortEntry("udp", "0.0.0.0", 8080),
        PortEntry("tcp", "192.168.1.2", 8080),
    ]
    result = snap.merge_sources(entries, (), (tunnel,))
    assert [r.hostname for r in result[0].tunnels] == ["app.example.com"]
    assert not result[1].tunnels and not result[2].tunnels


def test_local_interface_origin_can_match_wildcard() -> None:
    route = TunnelRoute(42, "app.example.com", "192.168.1.2", 8080)
    result = snap.merge_sources(
        [PortEntry("tcp", "0.0.0.0", 8080)],
        (),
        (TunnelInfo(42, (route,), "explicit"),),
        (LocalIP("en0", "192.168.1.2", "ipv4"),),
    )
    assert result[0].tunnels == (route,)


@pytest.mark.parametrize(
    "name,tag",
    [("kubelet", "k8s"), ("k3s", "k3s"), ("C:\\bin\\kubelite.exe", "microk8s")],
)
def test_tags_by_executable_name(name: str, tag: str) -> None:
    entry = PortEntry(
        "tcp", "127.0.0.1", 9999, 42, ProcessInfo(42, "ok", name, (name,))
    )
    result = tag_entry(entry)
    assert [(t.name, t.evidence) for t in result.tags] == [(tag, "process")]


def test_port_tag_is_explicitly_heuristic_and_protocol_specific() -> None:
    tcp = tag_entry(PortEntry("tcp", "127.0.0.1", 6443))
    assert [(t.name, t.evidence) for t in tcp.tags] == [("k8s", "port")]
    assert not tag_entry(PortEntry("udp", "127.0.0.1", 6443)).tags
    process = ProcessInfo(42, "ok", "python", ("python", "kubelet"))
    assert not tag_entry(PortEntry("tcp", "127.0.0.1", 9999, 42, process)).tags


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, Mock]:
    mocks = {
        "collect_listeners": Mock(return_value=[PortEntry("tcp", "0.0.0.0", 8080)]),
        "enrich_processes": Mock(side_effect=lambda entries: entries),
        "collect_local_ips": Mock(return_value=[]),
        "collect_docker": Mock(
            return_value=Collection((mapping(),), SourceReport("docker", "ok"))
        ),
        "collect_tunnels": Mock(
            return_value=Collection((), SourceReport("tunnels", "ok"))
        ),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(snap, name, mock)
    return mocks


def test_snapshot_is_json_serializable_and_merges_sources(
    sources: dict[str, Mock],
) -> None:
    result = snap.collect_snapshot()
    assert len(result.ports) == 1 and result.ports[0].docker
    data = json.loads(json.dumps(asdict(result)))
    assert set(data) == {"ports", "local_ips", "docker", "tunnels", "reports"}
    assert len(data["reports"]) == 5


def test_optional_source_failure_keeps_ports(sources: dict[str, Mock]) -> None:
    sources["collect_docker"].return_value = Collection(
        (), SourceReport("docker", "error")
    )
    sources["collect_tunnels"].return_value = Collection(
        (), SourceReport("tunnels", "unavailable")
    )
    sources["collect_local_ips"].side_effect = LocalIPError()
    result = snap.collect_snapshot()
    assert len(result.ports) == 1 and result.ports[0].origin == "socket"
    assert {r.source: r.status for r in result.reports}["docker"] == "error"


def test_failed_listener_read_still_exposes_docker_with_error_report(
    sources: dict[str, Mock],
) -> None:
    """Listener failures preserve Docker publications and a failure report."""
    sources["collect_listeners"].side_effect = ListenerAccessDenied()
    result = snap.collect_snapshot(accessible_fallback=False)
    assert result.ports[0].origin == "docker" and result.ports[0].pid is None
    assert result.reports[0].status == "unavailable"
    sources["enrich_processes"].assert_not_called()


def test_optional_sources_can_be_disabled(sources: dict[str, Mock]) -> None:
    result = snap.collect_snapshot(docker=False, tunnels=False)
    sources["collect_docker"].assert_not_called()
    sources["collect_tunnels"].assert_not_called()
    assert [r.status for r in result.reports[-2:]] == ["disabled", "disabled"]


def test_background_discovery_is_explicit_and_reuses_current_local_rows(
    sources: dict[str, Mock],
) -> None:
    discovery = Mock()
    discovery.collect.return_value = Collection(
        (), SourceReport("kubernetes", "partial")
    )
    snap.collect_snapshot(kube_discovery=discovery)
    discovery.collect.assert_not_called()
    result = snap.collect_snapshot(kube=True, kube_discovery=discovery)
    assert discovery.collect.call_args.args[0][0].docker
    assert discovery.collect.call_args.kwargs == {"timeout": 3.0}
    assert result.reports[-1].source == "kubernetes"


def test_nodeport_receives_tunnel_after_kube_merge(sources, monkeypatch):
    """Tunnel relations are attached after synthetic Kubernetes rows are added."""
    route = TunnelRoute(42, "node.example.test", "192.0.2.1", 31080)
    sources["collect_tunnels"].return_value = Collection(
        (TunnelInfo(42, (route,), "explicit"),), SourceReport("tunnels", "ok")
    )
    node = PortEntry("tcp", "192.0.2.1", 31080, origin="kubernetes")
    monkeypatch.setattr(
        snap,
        "collect_kube",
        lambda *args, **kwargs: Collection(
            (*args[0], node), SourceReport("kubernetes", "ok")
        ),
    )
    result = snap.collect_snapshot(kube=True)
    assert next(row for row in result.ports if row.origin == "kubernetes").tunnels == (
        route,
    )
    from portscanner.core.filtering import filter_entries

    assert filter_entries(result.ports, "node.example.test")[0].origin == "kubernetes"


@pytest.mark.parametrize(
    "bind,host,local,match",
    [
        ("*", "localhost", (), True),
        ("::1", "localhost", (), True),
        ("127.0.0.2", "localhost", (), True),
        ("192.0.2.1", "localhost", (), False),
        ("::", "127.0.0.1", (), False),
        ("0.0.0.0", "::1", (), False),
        ("::", "fe80::1%en0", (LocalIP("en0", "fe80::1%en0", "ipv6"),), True),
        ("fe80::1%en1", "fe80::1%en0", (), False),
        ("*", "remote.example", (), False),
    ],
)
def test_route_address_matrix(bind, host, local, match):
    route = TunnelRoute(1, "example.test", host, 80)
    entries = snap.merge_sources(
        [PortEntry("tcp", bind, 80)], (), (TunnelInfo(1, (route,)),), local
    )
    assert bool(entries[0].tunnels) is match


@pytest.mark.parametrize("source", ["net_connections", "net_if_addrs"])
def test_native_runtime_error_preserves_other_sources(sources, monkeypatch, source):
    """A native listener failure does not discard successful independent sources."""
    import psutil

    from portscanner.core.ips import collect_local_ips
    from portscanner.core.listeners import collect_listeners

    monkeypatch.setattr(snap, "collect_listeners", collect_listeners)
    monkeypatch.setattr(snap, "collect_local_ips", collect_local_ips)
    monkeypatch.setattr(psutil, "net_connections", Mock(return_value=[]))
    monkeypatch.setattr(psutil, "net_if_addrs", Mock(return_value={}))
    monkeypatch.setattr(
        psutil, source, Mock(side_effect=RuntimeError("native failure"))
    )
    result = snap.collect_snapshot()
    assert result.ports[0].docker
    failed = "listeners" if source == "net_connections" else "local_ips"
    assert next(r for r in result.reports if r.source == failed).status == "error"


def test_mac_fallback_is_partial_and_can_be_disabled(sources, monkeypatch):
    """The macOS accessible-process fallback is explicitly partial and optional."""
    from types import SimpleNamespace

    monkeypatch.setattr(snap, "sys", SimpleNamespace(platform="darwin"))
    sources["collect_listeners"].side_effect = ListenerAccessDenied("denied")
    fallback = Mock(
        return_value=Collection(
            (PortEntry("tcp", "127.0.0.1", 1234),), SourceReport("listeners", "partial")
        )
    )
    monkeypatch.setattr(snap, "collect_accessible_listeners", fallback)
    result = snap.collect_snapshot()
    assert result.reports[0].status == "partial"
    assert any(p.port == 1234 for p in result.ports)
    result = snap.collect_snapshot(accessible_fallback=False)
    assert result.reports[0].status == "unavailable"
    assert fallback.call_count == 1


def test_indexed_merge_only_compares_candidates_on_matching_port(monkeypatch):
    """Matching checks same-port candidates, not all cross-source pairs."""
    entries = [PortEntry("tcp", "0.0.0.0", 1000 + i) for i in range(300)]
    mappings = tuple(mapping(port=1000 + i) for i in range(300))
    routes = tuple(
        TunnelRoute(1, "example.test", "localhost", 1000 + i) for i in range(300)
    )
    docker_match = Mock(wraps=snap._docker_matches)
    route_match = Mock(wraps=snap._route_matches)
    monkeypatch.setattr(snap, "_docker_matches", docker_match)
    monkeypatch.setattr(snap, "_route_matches", route_match)
    rows = snap.merge_sources(entries, mappings, (TunnelInfo(1, routes),))
    assert len(rows) == 300 and all(row.docker and row.tunnels for row in rows)
    assert docker_match.call_count == route_match.call_count == 300
