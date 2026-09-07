"""Kontrakt użytkowy CLI: strumienie, kody, filtry, potwierdzenie i JSON."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from portscanner import cli
from portscanner.core.actions import KillTarget, ProcessActionError
from portscanner.core.ips import ExitIPError
from portscanner.core.model import (
    DockerPort,
    ExitIP,
    LocalIP,
    PortEntry,
    ProcessInfo,
    ServiceTag,
    Snapshot,
    SourceReport,
    TunnelRoute,
)

runner = CliRunner()


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> Mock:
    ports = (
        PortEntry(
            "tcp",
            "*",
            8080,
            42,
            ProcessInfo(42, "ok", "python", ("python", "server.py")),
            (DockerPort("abc", "web", "0.0.0.0", 8080, 80, "tcp", "demo", "web"),),
            (TunnelRoute(99, "app.example.com", "localhost", 8080, "/api"),),
            (ServiceTag("k8s", "port"),),
        ),
        PortEntry("udp", "::1", 5353),
    )
    snapshot = Snapshot(
        ports,
        (LocalIP("lo", "127.0.0.1", "ipv4"),),
        (),
        (),
        tuple(
            SourceReport(name, "ok")
            for name in ("listeners", "processes", "local_ips", "docker", "tunnels")
        ),
    )
    mock = Mock(return_value=snapshot)
    monkeypatch.setattr(cli, "collect_snapshot", mock)
    monkeypatch.setattr(
        cli,
        "fetch_exit_ip",
        Mock(side_effect=AssertionError("Nie wolno odpytując ipify")),
    )
    return mock


def test_json_golden_contract(source: Mock) -> None:
    result = runner.invoke(cli.app, ["--cli", "--json"], color=True)
    assert result.exit_code == 0, result.output
    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "cli_ports.json").read_text()
    )
    assert json.loads(result.stdout) == expected
    assert result.stderr == ""
    assert "\x1b" not in result.stdout and "IP lokalne" not in result.stdout


def test_default_launches_tui(source: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    from portscanner.tui import PortScannerApp

    launch = Mock()
    monkeypatch.setattr(PortScannerApp, "run", launch)
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    launch.assert_called_once_with()
    source.assert_not_called()


def test_help_never_scans(source: Mock) -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0 and "--json" in result.stdout
    source.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        ["--json"],
        ["--cli", "--filter", ":oops"],
        ["--cli", "--filter", ":65536"],
        ["--cli", "--filter", " "],
        ["--cli", "--filter", "pid:no"],
        ["--cli", "--force"],
        ["--cli", "--kill", "0"],
        ["--cli", "--kill", "42", "--json"],
        ["--cli", "--kill", "42", "--filter", ":80"],
        ["--cli", "--json", "--exit-ip"],
        ["--cli", "--timeout", "nan"],
        ["--cli", "--timeout", "inf"],
        ["--cli", "--timeout", "0"],
    ],
)
def test_invalid_options_fail_before_read_or_action(
    source: Mock, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    prepare = Mock()
    monkeypatch.setattr(cli, "prepare_kill", prepare)
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 2, result.output
    source.assert_not_called()
    prepare.assert_not_called()


@pytest.mark.parametrize(
    "query,ports",
    [
        (":8080", [8080]),
        ("pid:42", [8080]),
        ("PYTHON", [8080]),
        ("demo", [8080]),
        ("APP.EXAMPLE", [8080]),
        ("k8s", [8080]),
        ("::1", [5353]),
        ("udp", [5353]),
        ("not-present", []),
        (":80", []),
    ],
)
def test_filters(source: Mock, query: str, ports: list[int]) -> None:
    result = runner.invoke(cli.app, ["--cli", "--json", "--filter", query])
    assert result.exit_code == 0, result.output
    assert [entry["port"] for entry in json.loads(result.stdout)] == ports


def test_source_options_pass_through(source: Mock) -> None:
    runner.invoke(
        cli.app,
        [
            "--cli",
            "--json",
            "--no-docker",
            "--no-tunnels",
            "--no-metrics",
            "--timeout",
            "0.5",
        ],
    )
    source.assert_called_once_with(
        docker=False, tunnels=False, metrics=False, timeout=0.5
    )


def test_optional_warning_does_not_pollute_json(source: Mock) -> None:
    source.return_value = replace(
        source.return_value,
        reports=(
            SourceReport("listeners", "ok"),
            SourceReport("docker", "error", "daemon niedostępny"),
        ),
    )
    result = runner.invoke(cli.app, ["--cli", "--json"])
    assert result.exit_code == 0 and len(json.loads(result.stdout)) == 2
    assert "docker: error" in result.stderr


def test_listener_failure_returns_partial_json_and_failure_code(source: Mock) -> None:
    source.return_value = replace(
        source.return_value, reports=(SourceReport("listeners", "error"),)
    )
    result = runner.invoke(cli.app, ["--cli", "--json"])
    assert result.exit_code == 1 and len(json.loads(result.stdout)) == 2
    assert "listeners: error" in result.stderr


def test_empty_success_is_valid_empty_array(source: Mock) -> None:
    source.return_value = replace(source.return_value, ports=())
    result = runner.invoke(cli.app, ["--cli", "--json"])
    assert result.exit_code == 0 and result.stdout == "[]\n"


def test_table_has_columns_and_no_interpreted_markup(source: Mock) -> None:
    malicious = PortEntry(
        "tcp", "127.0.0.1", 80, 42, ProcessInfo(42, "ok", "[red]app\x1b[2J", ())
    )
    source.return_value = replace(source.return_value, ports=(malicious,))
    result = runner.invoke(
        cli.app, ["--cli", "--no-color"], color=True, env={"COLUMNS": "240"}
    )
    assert result.exit_code == 0
    for header in (
        "PROTO",
        "BIND",
        "PORT",
        "PID",
        "PROC",
        "DOCKER",
        "TUNNEL",
        "TAG",
        "ŹRÓDŁO",
    ):
        assert header in result.stdout
    assert "[red]app" in result.stdout and "\x1b" not in result.stdout


@pytest.mark.parametrize("failure", [False, True])
def test_exit_ip_is_explicit_and_errors_are_reported(
    source: Mock, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    fetch = Mock(return_value=ExitIP("8.8.8.8", "ipv4", "ipify"))
    if failure:
        fetch.side_effect = ExitIPError("brak sieci")
    monkeypatch.setattr(cli, "fetch_exit_ip", fetch)
    result = runner.invoke(cli.app, ["--cli", "--exit-ip"])
    assert result.exit_code == (1 if failure else 0)
    fetch.assert_called_once_with(timeout=3.0)
    assert (
        "brak sieci" in result.stderr
        if failure
        else "widziane z internetu" in result.stdout
    )


@pytest.fixture
def action(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    target = KillTarget(42, 123.0, "python", "/usr/bin/python", ("python", "server.py"))
    prepare, terminate = Mock(return_value=target), Mock()
    monkeypatch.setattr(cli, "prepare_kill", prepare)
    monkeypatch.setattr(cli, "terminate_target", terminate)
    return prepare, terminate


@pytest.mark.parametrize("answer", ["n\n", "\n", ""])
def test_kill_decline_or_eof_never_sends_signal(
    source: Mock, action: tuple[Mock, Mock], answer: str
) -> None:
    result = runner.invoke(cli.app, ["--cli", "--kill", "42"], input=answer)
    assert result.exit_code == 1
    action[1].assert_not_called()
    source.assert_not_called()


def test_force_still_confirms_and_uses_prepared_identity(
    source: Mock, action: tuple[Mock, Mock]
) -> None:
    result = runner.invoke(cli.app, ["--cli", "--kill", "42", "--force"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "python" in result.stderr and "server.py" in result.stderr
    assert "po timeout także kill" in result.stderr
    action[1].assert_called_once_with(action[0].return_value, force=True, timeout=3.0)
    source.assert_not_called()


def test_blocked_kill_never_prompts_or_terminates(
    source: Mock, action: tuple[Mock, Mock]
) -> None:
    action[0].side_effect = ProcessActionError("Proces chroniony")
    result = runner.invoke(cli.app, ["--cli", "--kill", "42"], input="y\n")
    assert result.exit_code == 1 and "Proces chroniony" in result.stderr
    assert "Zakończyć" not in result.stderr
    action[1].assert_not_called()
