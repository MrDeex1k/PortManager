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
    TunnelInfo,
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
        ["--cli", "--timeout", "1e300"],
        ["--cli", "--timeout", "3601"],
        ["--cli", "--json", "--json-snapshot"],
        ["--cli", "--json-snapshot", "--exit-ip"],
        ["--cli", "--json-snapshot", "--kill", "42"],
        ["--cli", "--columns", ""],
        ["--cli", "--columns", "PID,PID"],
        ["--cli", "--columns", "not-a-column"],
        ["--cli", "--json", "--columns", "PID"],
        ["--cli", "--json-snapshot", "--columns", "PID"],
        ["--cli", "--kill", "42", "--columns", "PID"],
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
        docker=False, tunnels=False, metrics=False, kube=False, timeout=0.5
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
    """Force still requires consent and preserves the identity displayed to the user."""
    action[0].return_value = replace(
        action[0].return_value,
        cmdline=("python", "server.py", "--token", "private-value"),
    )
    result = runner.invoke(cli.app, ["--cli", "--kill", "42", "--force"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "python" in result.stderr and "server.py" in result.stderr
    assert "private-value" not in result.output and "***" in result.stderr
    assert (
        "twarde zakończenie" if cli.os.name == "nt" else "po timeout także kill"
    ) in result.stderr
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


@pytest.mark.parametrize(
    "answer,called", [("y\n", True), ("n\n", False), ("\n", False), ("", False)]
)
def test_timeout_requires_a_second_consent(action, monkeypatch, answer, called):
    """A timeout continuation runs only after a separate affirmative response."""
    from portscanner.core.actions import TerminationPending

    pending = TerminationPending(action[0].return_value)
    resume = Mock(return_value="terminated")
    monkeypatch.setattr(pending.pending, "resume", resume)
    action[1].side_effect = pending
    result = runner.invoke(cli.app, ["--cli", "--kill", "42"], input="y\n" + answer)
    assert result.exit_code == (0 if called else 1)
    assert resume.call_count == int(called)
    assert "Wymusić" in result.output


@pytest.mark.parametrize("mode", [[], ["--gui"]])
@pytest.mark.parametrize(
    "options", [["--timeout", "3"], ["--json-snapshot"], ["--columns", "PORT"]]
)
def test_cli_only_options_are_rejected_even_at_default_values(
    source, monkeypatch, mode, options
):
    """Explicit defaults cannot silently select TUI or GUI and discard options."""
    from portscanner.tui import PortScannerApp

    tui_launch, gui_launch = Mock(), Mock()
    monkeypatch.setattr(PortScannerApp, "run", tui_launch)
    monkeypatch.setattr("portscanner.gui.launch", gui_launch)
    result = runner.invoke(cli.app, [*mode, *options])
    assert result.exit_code == 2
    source.assert_not_called()
    tui_launch.assert_not_called()
    gui_launch.assert_not_called()


@pytest.mark.parametrize(
    "status,code,exit_code",
    [
        ("partial", "udp_peer_unknown", 0),
        ("partial", None, 1),
        ("partial", "access_denied", 1),
        ("error", "udp_peer_unknown", 1),
    ],
)
def test_only_udp_peer_limitation_allows_success(source, status, code, exit_code):
    """Metadata limitations do not masquerade as incomplete listener enumeration."""
    source.return_value = replace(
        source.return_value, reports=(SourceReport("listeners", status, code=code),)
    )
    result = runner.invoke(cli.app, ["--cli", "--json", "--filter", "tcp"])
    assert result.exit_code == exit_code
    assert json.loads(result.stdout)
    assert "listeners: " + status in result.stderr
    if code:
        assert f"[{code}]" in result.stderr


def test_connectors_and_codes_are_visible_without_port_matches(source):
    """A token connector and a failed connector survive an empty port filter."""
    source.return_value = replace(
        source.return_value,
        tunnels=(
            TunnelInfo(
                998877, config_status="remote", metrics_status="ok", connections=4
            ),
            TunnelInfo(
                998878,
                config_status="error",
                config_code="unsafe_file",
                metrics_status="error",
                metrics_code="timeout",
            ),
        ),
        reports=(
            SourceReport("listeners", "ok"),
            SourceReport(
                "kubernetes",
                "error",
                "Odczyt klastra niedostępny.",
                code="config_changed",
            ),
        ),
    )
    result = runner.invoke(
        cli.app,
        ["--cli", "--filter", "no-match", "--no-color"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0
    assert "PID 998877" in result.stdout and "połączenia=4" in result.stdout
    assert "config=remote" in result.stdout
    assert "unsafe_file" in result.stdout and "timeout" in result.stdout
    assert "config_changed" in result.stderr


def test_snapshot_json_preserves_metadata_when_ports_are_filtered(source):
    """The opt-in object export retains diagnostics without altering the list mode."""
    source.return_value = replace(
        source.return_value,
        tunnels=(
            TunnelInfo(998877, config_status="remote", metrics_status="disabled"),
        ),
        reports=(
            SourceReport("listeners", "ok"),
            SourceReport("docker", "error", code="timeout"),
        ),
    )
    result = runner.invoke(
        cli.app, ["--cli", "--json-snapshot", "--filter", "no-match"]
    )
    data = json.loads(result.stdout)
    assert result.exit_code == 0
    assert data["ports"] == []
    assert data["tunnels"][0]["pid"] == 998877
    assert data["reports"][1]["code"] == "timeout"
    assert data["local_ips"][0]["address"] == "127.0.0.1"
    assert "\x1b" not in result.stdout
    assert "timeout" in result.stderr


def test_table_columns_can_be_selected_in_order(source):
    """A compact table omits unused integrations without changing its data source."""
    result = runner.invoke(
        cli.app, ["--cli", "--columns", "pid,port,proc", "--no-color"]
    )
    assert result.exit_code == 0
    assert (
        result.stdout.index("PID")
        < result.stdout.index("PORT")
        < result.stdout.index("PROC")
    )
    assert "KUBERNETES" not in result.stdout and "DOCKER" not in result.stdout
    assert "8080" in result.stdout and "python" in result.stdout


def test_explicit_default_timeout_remains_valid_for_cli(source):
    result = runner.invoke(cli.app, ["--cli", "--json", "--timeout", "3"])
    assert result.exit_code == 0
    assert source.call_args.kwargs["timeout"] == 3.0
