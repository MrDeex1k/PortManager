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
    sources["collect_listeners"].side_effect = ListenerAccessDenied()
    result = snap.collect_snapshot()
    assert result.ports[0].origin == "docker" and result.ports[0].pid is None
    assert result.reports[0].status == "error"
    sources["enrich_processes"].assert_not_called()


def test_optional_sources_can_be_disabled(sources: dict[str, Mock]) -> None:
    result = snap.collect_snapshot(docker=False, tunnels=False)
    sources["collect_docker"].assert_not_called()
    sources["collect_tunnels"].assert_not_called()
    assert [r.status for r in result.reports[-2:]] == ["disabled", "disabled"]
