"""Opcjonalny Kubernetes: pochodzenie, lokalność i degradacja odczytu."""

import json
import subprocess
from dataclasses import replace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from portscanner import cli
from portscanner.core import kube, snapshot
from portscanner.core.filtering import filter_entries
from portscanner.core.model import (
    Collection,
    LocalIP,
    PortEntry,
    ProcessInfo,
    SourceReport,
)
from portscanner.gui.app import DesktopAPI
from portscanner.presentation import entry_cells


def listing(*items: dict) -> str:
    return json.dumps({"items": items})


def services(proto: str = "TCP", node_port: object = 31080) -> str:
    return listing(
        {
            "kind": "Service",
            "metadata": {"name": "web", "namespace": "demo"},
            "spec": {
                "type": "NodePort",
                "ports": [
                    {"port": 80, "nodePort": node_port, "protocol": proto},
                ],
            },
        }
    )


def nodes(address: str = "192.0.2.1") -> str:
    return listing(
        {
            "kind": "Node",
            "metadata": {"name": "worker"},
            "status": {
                "addresses": [{"type": "InternalIP", "address": address}],
            },
        }
    )


IPS = (LocalIP("en0", "192.0.2.1", "ipv4"),)


def forward(*args: str) -> PortEntry:
    return PortEntry(
        "tcp",
        "127.0.0.1",
        8080,
        42,
        ProcessInfo(
            42,
            "ok",
            "kubectl",
            ("/usr/bin/kubectl", *args),
        ),
    )


@pytest.mark.parametrize("proto", ["TCP", "UDP"])
def test_nodeport_is_configuration_not_a_socket_or_process(proto: str) -> None:
    result = kube.parse_nodeports(services(proto), nodes(), IPS)
    (row,) = result
    assert (row.bind, row.port, row.proto) == ("192.0.2.1", 31080, proto.lower())
    assert row.origin == "kubernetes" and row.pid is None and row.process is None
    assert row.kubernetes[0].namespace == "demo"
    assert row.kubernetes[0].resource == "service/web"
    assert row.kubernetes[0].remote_port == "80"
    assert filter_entries(result, "demo") == list(result)
    assert filter_entries(result, "worker") == list(result)
    assert any("nodeport" in cell for cell in entry_cells(row))


def test_remote_cluster_never_creates_local_rows() -> None:
    assert not kube.parse_nodeports(services(), nodes("192.0.2.99"), IPS)
    assert not kube.parse_nodeports(services(), nodes(), ())
    loopback = (LocalIP("lo", "127.0.0.1", "ipv4"),)
    assert not kube.parse_nodeports(services(), nodes("127.0.0.1"), loopback)


def test_ipv6_and_custom_nodeport_range() -> None:
    ips = (LocalIP("en0", "2001:db8::1", "ipv6"),)
    (row,) = kube.parse_nodeports(services(node_port=12345), nodes("2001:db8::1"), ips)
    assert row.bind == "2001:db8::1" and row.port == 12345


def test_clusterip_sctp_and_unallocated_ports_are_ignored() -> None:
    assert not kube.parse_nodeports(services("SCTP"), nodes(), IPS)
    assert not kube.parse_nodeports(services(node_port=None), nodes(), IPS)
    assert not kube.parse_nodeports(
        services().replace("NodePort", "ClusterIP"), nodes(), IPS
    )


@pytest.mark.parametrize("invalid", [True, -1, 65536, "31080"])
def test_invalid_nodeport_is_rejected(invalid: object) -> None:
    with pytest.raises(ValueError):
        kube.parse_nodeports(services(node_port=invalid), nodes(), IPS)


@pytest.mark.parametrize(
    "args",
    [
        ("-n", "demo", "port-forward", "svc/web", "8080:http", "--context=dev"),
        (
            "port-forward",
            "svc/web",
            "8080:http",
            "--namespace=demo",
            "--context",
            "dev",
        ),
    ],
)
def test_forward_matches_pid_socket_and_preserves_explicit_context(
    args: tuple[str, ...],
) -> None:
    row = forward(*args)
    (mapping,) = kube.port_forward(row)
    assert (mapping.namespace, mapping.context, mapping.remote_port) == (
        "demo",
        "dev",
        "http",
    )
    assert not kube.port_forward(replace(row, port=8081))
    assert not kube.port_forward(replace(row, pid=43))
    assert not kube.port_forward(replace(row, proto="udp"))
    assert not kube.port_forward(replace(row, origin="docker"))


def test_forward_does_not_guess_namespace_or_context() -> None:
    (mapping,) = kube.port_forward(forward("port-forward", "pod/web", "8080"))
    assert mapping.namespace is None and mapping.context is None
    assert mapping.remote_port == "8080"


@pytest.mark.parametrize(
    "args",
    [
        ("get", "pods", "8080:80"),
        ("port-forward", "svc/web", ":80"),
        ("port-forward", "svc/web", "8080:65536"),
        ("port-forward", "svc/web", "8080:80", "--unknown", "x"),
        ("port-forward", "svc/web", "8080:80", "--context"),
        ("--context", "port-forward", "get", "svc/web", "8080:80"),
    ],
)
def test_forward_ambiguous_arguments_are_not_guessed(args: tuple[str, ...]) -> None:
    assert not kube.port_forward(forward(*args))


def test_process_name_alone_does_not_match() -> None:
    row = forward("port-forward", "svc/web", "8080:80")
    assert row.process is not None
    row = replace(row, process=replace(row.process, name="python"))
    assert not kube.port_forward(row)


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(),
        subprocess.TimeoutExpired("kubectl", 3),
        subprocess.CalledProcessError(1, "kubectl", stderr="secret-token"),
        ValueError("secret-data"),
    ],
)
def test_cluster_failure_preserves_ports_and_forward_without_exposing_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    monkeypatch.setattr(kube, "_run", Mock(side_effect=error))
    row = forward("port-forward", "svc/web", "8080:80")
    result = kube.collect_kube((row,), IPS)
    assert result.items[0].pid == 42 and result.items[0].kubernetes
    assert result.report.status == "partial"
    assert "secret" not in (result.report.message or "")


def test_single_invocation_pins_config_for_both_resource_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    combined = listing(*json.loads(services())["items"], *json.loads(nodes())["items"])
    run = Mock(return_value=combined)
    monkeypatch.setattr(kube, "_run", run)
    result = kube.collect_kube((), IPS, timeout=3)
    assert result.report.status == "ok" and result.items[0].kubernetes
    run.assert_called_once_with("services,nodes", 3)


def test_snapshot_optin_and_bridge_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(snapshot, "collect_listeners", Mock(return_value=[]))
    monkeypatch.setattr(snapshot, "collect_local_ips", Mock(return_value=list(IPS)))
    rows = kube.parse_nodeports(services(), nodes(), IPS)
    collect = Mock(return_value=Collection(rows, SourceReport("kubernetes", "ok")))
    monkeypatch.setattr(snapshot, "collect_kube", collect)
    snapshot.collect_snapshot(docker=False, tunnels=False)
    collect.assert_not_called()
    result = snapshot.collect_snapshot(docker=False, tunnels=False, kube=True)
    collect.assert_called_once_with((), IPS, timeout=3.0)
    api = DesktopAPI(collector=lambda: result)
    payload = api.read_snapshot(1)
    assert payload["ports"][0]["kubernetes"][0]["kind"] == "nodeport"
    assert payload["ports"][0]["pid"] is None


def test_cli_gui_tui_route_kube_option(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    launch = Mock()
    monkeypatch.setattr("portscanner.gui.launch", launch)
    assert runner.invoke(cli.app, ["--gui", "--kube"]).exit_code == 0
    launch.assert_called_once_with(kube=True)
    tui = Mock()
    monkeypatch.setattr("portscanner.tui.PortScannerApp", tui)
    assert runner.invoke(cli.app, ["--kube"]).exit_code == 0
    tui.assert_called_once_with(kube=True)
    tui.return_value.run.assert_called_once_with()
    assert runner.invoke(cli.app, ["--cli", "--kube", "--kill", "42"]).exit_code == 2


def test_compact_namespace_flag() -> None:
    (mapping,) = kube.port_forward(
        forward("-ndemo", "port-forward", "svc/web", "8080:80")
    )
    assert mapping.namespace == "demo"


@pytest.mark.parametrize(
    "output", ["null", '{"items": null}', '{"items": [null]}', "{"]
)
def test_bad_cluster_json_degrades_without_losing_socket(
    monkeypatch: pytest.MonkeyPatch, output: str
) -> None:
    monkeypatch.setattr(kube, "_run", Mock(side_effect=[output, nodes()]))
    row = PortEntry("tcp", "127.0.0.1", 80)
    result = kube.collect_kube((row,), IPS)
    assert result.items == (row,)
    assert result.report.status == "error"


def test_loadbalancer_multiple_services_share_one_configuration_row() -> None:
    first = json.loads(services())["items"][0]
    second = json.loads(services())["items"][0]
    second["metadata"]["name"] = "another"
    second["spec"]["type"] = "LoadBalancer"
    (row,) = kube.parse_nodeports(listing(first, second), nodes(), IPS)
    assert len(row.kubernetes) == 2
    assert {m.resource for m in row.kubernetes} == {"service/web", "service/another"}


def test_cli_kube_json_and_partial_source_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from portscanner.core.model import Snapshot

    rows = kube.parse_nodeports(services(), nodes(), IPS)
    result = Snapshot(
        rows,
        IPS,
        (),
        (),
        (
            SourceReport("listeners", "ok"),
            SourceReport("kubernetes", "partial", "Niepełne dane"),
        ),
    )
    collect = Mock(return_value=result)
    monkeypatch.setattr(cli, "collect_snapshot", collect)
    response = CliRunner().invoke(cli.app, ["--cli", "--kube", "--json"])
    assert response.exit_code == 0
    assert collect.call_args.kwargs["kube"] is True
    assert json.loads(response.stdout)[0]["kubernetes"][0]["resource"] == "service/web"
    assert "kubernetes: partial" in response.stderr


def test_nodeports_are_interleaved_in_snapshot_contract_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    combined = listing(*json.loads(services())["items"], *json.loads(nodes())["items"])
    monkeypatch.setattr(kube, "_run", Mock(return_value=combined))
    entries = (
        PortEntry("tcp", "192.0.2.1", 40000, 10),
        PortEntry("udp", "192.0.2.1", 31080, 3),
        PortEntry("tcp", "192.0.2.2", 31080, 1),
        PortEntry("tcp", "192.0.2.1", 31080, 7),
        PortEntry("tcp", "192.0.2.1", 31080),
        PortEntry("tcp", "127.0.0.1", 80, 8),
    )
    result = kube.collect_kube(entries, IPS)
    assert result.report.status == "ok"
    assert [
        (row.port, row.proto, row.bind, row.pid, row.origin) for row in result.items
    ] == [
        (80, "tcp", "127.0.0.1", 8, "socket"),
        (31080, "tcp", "192.0.2.1", None, "kubernetes"),
        (31080, "tcp", "192.0.2.1", None, "socket"),
        (31080, "tcp", "192.0.2.1", 7, "socket"),
        (31080, "tcp", "192.0.2.2", 1, "socket"),
        (31080, "udp", "192.0.2.1", 3, "socket"),
        (40000, "tcp", "192.0.2.1", 10, "socket"),
    ]
    assert result.items[1].kubernetes[0].resource == "service/web"
