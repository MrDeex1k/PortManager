"""Wejście GUI, izolacja dodatku i wybór zaufanych zasobów."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from portscanner.cli import app
from portscanner.gui import GuiLaunchError
from portscanner.gui import app as gui


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


def test_bridge_exposes_preview_metadata_only() -> None:
    info = gui.DesktopAPI().get_app_info()
    assert info["mode"] == "desktop" and info["stage"] == "preview"
    assert [name for name in dir(gui.DesktopAPI) if not name.startswith("_")] == [
        "get_app_info"
    ]
