"""Wejście GUI, izolacja dodatku i wybór zaufanych zasobów."""

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from portscanner.cli import app
from portscanner.core.actions import KillTarget, ProcessActionError
from portscanner.core.model import (
    LocalIP,
    PortEntry,
    ProcessInfo,
    Snapshot,
    SourceReport,
)
from portscanner.gui import GuiLaunchError
from portscanner.gui import app as gui


def _snapshot(*ports: PortEntry) -> Snapshot:
    return Snapshot(
        ports=ports,
        local_ips=(LocalIP("lo0", "127.0.0.1", "ipv4"),),
        docker=(),
        tunnels=(),
        reports=(SourceReport("processes", "partial", "Część danych niedostępna."),),
    )


def test_gui_launch_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    launch = Mock()
    monkeypatch.setattr("portscanner.gui.launch", launch)
    result = CliRunner().invoke(app, ["--gui"])
    assert result.exit_code == 0, result.output
    launch.assert_called_once_with()


@pytest.mark.parametrize(
    "args",
    [
        ["--cli"],
        ["--kill", "42"],
        ["--json"],
        ["--filter", ":80"],
        ["--no-docker"],
        ["--force"],
        ["--exit-ip"],
        ["--timeout", "2"],
    ],
)
def test_gui_rejects_cli_options(
    args: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    launch = Mock()
    monkeypatch.setattr("portscanner.gui.launch", launch)
    result = CliRunner().invoke(app, ["--gui", *args])
    assert result.exit_code == 2
    launch.assert_not_called()


def test_cli_import_does_not_load_optional_gui() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, json; import portscanner.cli; "
            "print(json.dumps([m for m in sys.modules "
            "if m == 'webview' or m.startswith('portscanner.gui')]))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == []


def test_missing_gui_dependency_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui.importlib, "import_module", Mock(side_effect=ImportError))
    result = CliRunner().invoke(app, ["--gui"])
    assert result.exit_code == 1
    assert "uv sync --locked --extra gui" in result.stderr


def test_missing_assets_are_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui, "__file__", str(tmp_path / "app.py"))
    with pytest.raises(GuiLaunchError, match="bun run build"):
        gui._window_url(None)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5173@evil.test",
        "http://127.0.0.1:5173/path",
        "",
    ],
)
def test_dev_url_rejects_other_origins(url: str) -> None:
    with pytest.raises(GuiLaunchError):
        gui._window_url(url)


def test_packaged_assets_resolve_outside_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = tmp_path / "gui" / "assets" / "index.html"
    entry.parent.mkdir(parents=True)
    entry.write_text("<html></html>")
    monkeypatch.setattr(gui, "__file__", str(tmp_path / "gui" / "app.py"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PORTSCANNER_GUI_DEV_URL", raising=False)
    webview = Mock()
    monkeypatch.setattr(gui.importlib, "import_module", Mock(return_value=webview))
    gui.launch()
    assert webview.create_window.call_args.args == ("PortManager", str(entry))
    assert isinstance(webview.create_window.call_args.kwargs["js_api"], gui.DesktopAPI)
    webview.start.assert_called_once_with(http_server=True, debug=False, icon=None)


def test_vite_launch_uses_existing_loopback_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PORTSCANNER_GUI_DEV_URL", "http://127.0.0.1:5173")
    webview = Mock()
    monkeypatch.setattr(gui.importlib, "import_module", Mock(return_value=webview))
    gui.launch()
    assert webview.create_window.call_args.args[1] == "http://127.0.0.1:5173/?desktop=1"
    assert webview.start.call_args.kwargs["http_server"] is False
    assert webview.start.call_args.kwargs["debug"] is False


def test_window_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTSCANNER_GUI_DEV_URL", "http://127.0.0.1:5173")
    webview = Mock()
    webview.start.side_effect = RuntimeError("no display")
    monkeypatch.setattr(gui.importlib, "import_module", Mock(return_value=webview))
    result = CliRunner().invoke(app, ["--gui"])
    assert result.exit_code == 1
    assert "sesję graficzną" in result.stderr


def test_bridge_exposes_live_metadata_and_operations() -> None:
    info = gui.DesktopAPI().get_app_info()
    assert info["mode"] == "desktop" and info["stage"] == "live"
    assert set(name for name in dir(gui.DesktopAPI) if not name.startswith("_")) == {
        "export_ports",
        "filter_ports",
        "get_app_info",
        "prepare_process",
        "read_snapshot",
        "terminate_process",
    }


def test_bridge_serializes_snapshot_and_uses_core_filter() -> None:
    api = gui.DesktopAPI(
        collector=lambda: _snapshot(
            PortEntry(
                "tcp",
                "127.0.0.1",
                3000,
                42,
                ProcessInfo(42, "ok", "bun", ("bun", "dev")),
            ),
            PortEntry("udp", "*", 5353),
        )
    )
    result = api.read_snapshot(7)
    assert result["ok"] is True
    assert result["request_id"] == 7
    assert result["ports"][0]["process"]["cmdline"] == ("bun", "dev")
    assert result["local_ips"] == [
        {"interface": "lo0", "address": "127.0.0.1", "family": "ipv4"}
    ]
    assert result["reports"] == [
        {
            "source": "processes",
            "status": "partial",
            "message": "Część danych niedostępna.",
        }
    ]
    filtered = api.filter_ports(result["generation"], ":3000")
    assert filtered == {
        "ok": True,
        "generation": result["generation"],
        "ids": [result["ports"][0]["id"]],
    }
    invalid = api.filter_ports(result["generation"], "pid:")
    assert invalid["ok"] is False and "liczby" in invalid["message"]


def test_bridge_does_not_overlap_slow_reads() -> None:
    started = threading.Event()
    release = threading.Event()

    def slow() -> Snapshot:
        started.set()
        release.wait(timeout=2)
        return _snapshot()

    api = gui.DesktopAPI(collector=slow)
    worker = threading.Thread(target=api.read_snapshot, args=(1,))
    worker.start()
    assert started.wait(timeout=1)
    assert api.read_snapshot(2) == {"ok": False, "busy": True, "request_id": 2}
    release.set()
    worker.join(timeout=1)


def test_bridge_reports_collection_error_without_details() -> None:
    def fail() -> Snapshot:
        raise RuntimeError("sensitive details")

    result = gui.DesktopAPI(collector=fail).read_snapshot(1)
    assert result == {
        "ok": False,
        "message": "Nie udało się zebrać migawki systemu.",
        "request_id": 1,
    }


def test_export_preserves_visible_order_and_cli_contract(tmp_path: Path) -> None:
    first = PortEntry("tcp", "127.0.0.1", 3000, 42)
    second = PortEntry("udp", "*", 5353)
    api = gui.DesktopAPI(collector=lambda: _snapshot(first, second))
    snapshot = api.read_snapshot(1)
    output = tmp_path / "ports.json"
    window = Mock()
    window.create_file_dialog.return_value = (str(output),)
    api._attach_window(window, "save")
    result = api.export_ports(
        snapshot["generation"],
        [snapshot["ports"][1]["id"], snapshot["ports"][0]["id"]],
    )
    assert result == {"ok": True, "status": "saved", "path": str(output)}
    assert json.loads(output.read_text()) == [
        json.loads(json.dumps(gui.asdict(second))),
        json.loads(json.dumps(gui.asdict(first))),
    ]


def test_kill_consent_is_redacted_fixed_and_single_use() -> None:
    target = KillTarget(42, 1.5, "bun", "/usr/bin/bun", ("bun", "--token", "secret"))
    terminate = Mock()
    api = gui.DesktopAPI(prepare=lambda pid: target, terminate=terminate)
    prepared = api.prepare_process(42)
    assert prepared["target"]["cmdline"] == ["bun", "--token", "***"]
    assert api.terminate_process(prepared["token"], True)["ok"] is True
    terminate.assert_called_once_with(target, force=True, timeout=3.0)
    assert api.terminate_process(prepared["token"], False)["ok"] is False


def test_kill_policy_error_is_visible() -> None:
    def deny(pid: int) -> KillTarget:
        raise ProcessActionError("Proces jest chroniony.")

    result = gui.DesktopAPI(prepare=deny).prepare_process(42)
    assert result == {"ok": False, "message": "Proces jest chroniony."}


def test_terminate_error_is_visible_and_consent_is_consumed() -> None:
    target = KillTarget(42, 1.5, "bun", "/usr/bin/bun", ("bun", "dev"))

    def timeout(*args: object, **kwargs: object) -> None:
        raise ProcessActionError("Proces nie zakończył się przed timeoutem.")

    api = gui.DesktopAPI(prepare=lambda pid: target, terminate=timeout)
    prepared = api.prepare_process(42)
    result = api.terminate_process(prepared["token"], False)
    assert result == {
        "ok": False,
        "message": "Proces nie zakończył się przed timeoutem.",
    }
    assert api.terminate_process(prepared["token"], False)["ok"] is False


def test_bridge_rejects_malformed_action_arguments() -> None:
    api = gui.DesktopAPI(collector=lambda: _snapshot())
    snapshot = api.read_snapshot(1)
    malformed_ids: Any = [1]
    malformed_token: Any = []
    malformed_force: Any = "false"
    assert api.export_ports(snapshot["generation"], malformed_ids)["ok"] is False
    assert api.terminate_process(malformed_token, False)["ok"] is False
    assert api.terminate_process("token", malformed_force)["ok"] is False
