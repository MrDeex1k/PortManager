"""Docker: porty strukturalne, kontekst lokalny i awarie CLI."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from portscanner.core import docker


def record(**changes: object) -> str:
    row: dict[str, object] = {
        "id": "a" * 64,
        "name": "/web",
        "running": True,
        "ports": {
            "80/tcp": [
                {"HostIp": "0.0.0.0", "HostPort": "8080"},
                {"HostIp": "::", "HostPort": "8080"},
            ],
            "53/udp": [{"HostIp": "127.0.0.1", "HostPort": "5353"}],
            "443/tcp": None,
        },
        "project": "my-project",
        "service": "web",
    }
    row.update(changes)
    return json.dumps(row)


def test_structural_ports_keep_family_protocol_and_compose() -> None:
    ports = docker.parse_inspect(record())
    assert [(p.proto, p.host_bind, p.host_port, p.container_port) for p in ports] == [
        ("udp", "127.0.0.1", 5353, 53),
        ("tcp", "0.0.0.0", 8080, 80),
        ("tcp", "::", 8080, 80),
    ]
    assert all(
        p.container_name == "web"
        and p.compose_project == "my-project"
        and p.compose_service == "web"
        for p in ports
    )
    assert docker.parse_inspect(record() + "\n" + record()) == ports


def test_stopped_unpublished_and_host_network_do_not_invent_ports() -> None:
    assert docker.parse_inspect(record(running=False)) == ()
    assert docker.parse_inspect(record(ports=None)) == ()
    assert docker.parse_inspect(record(ports={"80/tcp": None})) == ()


@pytest.mark.parametrize(
    "output",
    [
        "not json",
        "[]",
        record(ports={"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "0"}]}),
        record(ports={"80/tcp": [{"HostIp": "bad host", "HostPort": "8080"}]}),
    ],
)
def test_invalid_records_are_rejected(output: str) -> None:
    with pytest.raises(ValueError):
        docker.parse_inspect(output)


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, '"unix:///tmp/docker.sock"'),
            subprocess.CompletedProcess([], 0, json.dumps({"ID": "a" * 64})),
            subprocess.CompletedProcess([], 0, record()),
        ]
    )
    monkeypatch.setattr(subprocess, "run", run)
    return run


def test_cli_uses_local_endpoint_timeout_and_inspect_projection(runner: Mock) -> None:
    result = docker.collect_docker(timeout=1.5)
    assert result.report.status == "ok" and len(result.items) == 3
    commands = [call.args[0] for call in runner.call_args_list]
    assert commands[1][:3] == ["docker", "--host", "unix:///tmp/docker.sock"]
    assert "ps" in commands[1] and "inspect" in commands[2]
    assert "--type" in commands[2]
    for call in runner.call_args_list:
        assert call.kwargs["timeout"] == 1.5
        assert call.kwargs.get("shell", False) is False
    assert ".Env" not in commands[2][commands[2].index("--format") + 1]


@pytest.mark.parametrize("endpoint", ["ssh://server", "tcp://127.0.0.1:2375"])
def test_non_socket_endpoints_never_contact_daemon(runner: Mock, endpoint: str) -> None:
    runner.side_effect = [subprocess.CompletedProcess([], 0, json.dumps(endpoint))]
    assert docker.collect_docker().report.status == "unavailable"
    assert runner.call_count == 1


def test_explicit_remote_host_is_skipped_without_cli(
    runner: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote")
    assert docker.collect_docker().report.status == "unavailable"
    runner.assert_not_called()


def test_context_takes_precedence_over_host(
    runner: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote")
    monkeypatch.setenv("DOCKER_CONTEXT", "desktop-linux")
    assert docker.collect_docker().report.status == "ok"
    assert "desktop-linux" in runner.call_args_list[0].args[0]
    assert "DOCKER_CONTEXT" not in runner.call_args_list[1].kwargs["env"]


@pytest.mark.parametrize(
    "error,status",
    [
        (FileNotFoundError(), "unavailable"),
        (subprocess.TimeoutExpired("docker", 1), "error"),
        (subprocess.CalledProcessError(1, "docker", stderr="secret"), "error"),
        (PermissionError(), "error"),
    ],
)
def test_cli_errors_become_reports(runner: Mock, error: Exception, status: str) -> None:
    runner.side_effect = error
    result = docker.collect_docker()
    assert result.report.status == status and not result.items
    assert "secret" not in str(result)
