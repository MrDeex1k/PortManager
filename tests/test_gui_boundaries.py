"""Regression tests for bridge isolation, shutdown and atomic private exports."""

import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from portscanner.core.actions import KillTarget, TerminationPending
from portscanner.core.model import PortEntry, Snapshot
from portscanner.gui import app as gui


def snapshot():
    return Snapshot(
        ports=(PortEntry("tcp", "::1", 8080),),
        local_ips=(),
        docker=(),
        tunnels=(),
        reports=(),
    )


@pytest.fixture
def api():
    instance = gui.DesktopAPI(collector=snapshot)
    yield instance
    instance._close()


def prepare_export(api, path):
    result = api.read_snapshot(1)
    assert result["ok"]
    window = Mock()
    window.create_file_dialog.return_value = (str(path),)
    api._attach_window(window, "save")
    return result["generation"], [p["id"] for p in result["ports"]]


def test_dispatcher_cannot_reach_private_or_nested_methods(monkeypatch):
    util = pytest.importorskip("webview.util")
    webview = MagicMock()
    probe = Mock()
    native = webview.create_window.return_value
    native.probe = probe
    monkeypatch.setenv("PORTSCANNER_GUI_DEV_URL", "http://127.0.0.1:5173")
    monkeypatch.setattr(gui.importlib, "import_module", Mock(return_value=webview))

    def check_dispatcher(**kwargs):
        assert "js_api" not in webview.create_window.call_args.kwargs
        exposed = native.expose.call_args.args
        functions = {method.__name__: method for method in exposed}
        api = functions["get_app_info"].__self__
        finished = threading.Event()
        responses = []

        def returned(script):
            responses.append(script)
            finished.set()

        window = SimpleNamespace(
            _js_api=None, _functions=functions, evaluate_js=returned
        )
        for name in ("_close", "_window.probe", "get_app_info.__self__._close"):
            util.js_bridge_call(window, name, [], "audit")
        assert not api._closed
        probe.assert_not_called()
        assert not responses
        util.js_bridge_call(window, "get_app_info", [], "audit")
        assert finished.wait(2)
        assert "PortManager" in responses[0]
        assert "isError" not in responses[0]

    webview.start.side_effect = check_dispatcher
    gui.launch()


@pytest.mark.parametrize("generation", [True, False, 1.0, "1", None])
def test_export_rejects_non_integer_generations(api, tmp_path, generation):
    _, ids = prepare_export(api, tmp_path / "out.json")
    assert api.export_ports(generation, ids)["code"] == "invalid_request"
    api._window.create_file_dialog.assert_not_called()


@pytest.mark.parametrize("stage", ["serialization", "replace", "fsync"])
def test_failed_export_preserves_destination_and_removes_temporary(
    api, tmp_path, monkeypatch, stage
):
    path = tmp_path / "ports.json"
    path.write_text("ORIGINAL")
    args = prepare_export(api, path)

    def interrupted(entries, stream):
        stream.write("PARTIAL")
        raise OSError("private disk details")

    if stage == "serialization":
        monkeypatch.setattr(gui, "write_ports_json", interrupted)
    else:
        monkeypatch.setattr(gui.os, stage, Mock(side_effect=OSError("private details")))
    result = api.export_ports(*args)
    assert result["code"] == "export_failed"
    assert "private" not in str(result)
    assert path.read_text() == "ORIGINAL"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
@pytest.mark.parametrize("existing_mode", [None, 0o644, 0o600, 0o400])
def test_export_is_private_and_never_broadens_mode(api, tmp_path, existing_mode):
    path = tmp_path / "ports.json"
    if existing_mode is not None:
        path.write_text("ORIGINAL")
        path.chmod(existing_mode)
    args = prepare_export(api, path)
    assert api.export_ports(*args)["ok"]
    assert stat.S_IMODE(path.stat().st_mode) == (
        0o600 if existing_mode is None else existing_mode & 0o600
    )


def test_exports_are_serialized_and_dialog_exception_is_safe(api, tmp_path):
    args = prepare_export(api, tmp_path / "ports.json")
    entered, release = threading.Event(), threading.Event()

    def dialog(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        raise RuntimeError("native backend secret")

    api._window.create_file_dialog.side_effect = dialog
    with ThreadPoolExecutor() as pool:
        first = pool.submit(api.export_ports, *args)
        try:
            assert entered.wait(2)
            assert api.export_ports(*args)["code"] == "busy"
        finally:
            release.set()
        result = first.result(2)
    assert result["code"] == "export_failed"
    assert "secret" not in str(result)
    api._window.create_file_dialog.side_effect = None
    assert api.export_ports(*args)["ok"]


def test_close_discards_inflight_snapshot_and_rejects_new_operations(api):
    entered, release = threading.Event(), threading.Event()

    def slow():
        entered.set()
        assert release.wait(2)
        return snapshot()

    api._collector = slow
    with ThreadPoolExecutor() as pool:
        future = pool.submit(api.read_snapshot, 1)
        try:
            assert entered.wait(2)
            api._close()
        finally:
            release.set()
        assert future.result(2)["code"] == "app_closed"
    assert api._snapshot is None
    operations = (
        (api.read_snapshot, (2,)),
        (api.export_ports, (1, [])),
        (api.filter_ports, (1, None)),
        (api.set_kubernetes, (True,)),
        (api.get_app_info, ()),
        (api.prepare_process, (42,)),
        (api.terminate_process, ("token",)),
        (api.cancel_process, ("token",)),
    )
    for method, args in operations:
        assert method(*args)["code"] == "app_closed"


@pytest.mark.parametrize("stage", ["dialog", "write"])
def test_close_cancels_export_before_publication(api, tmp_path, monkeypatch, stage):
    path = tmp_path / "ports.json"
    path.write_text("ORIGINAL")
    args = prepare_export(api, path)
    if stage == "dialog":

        def dialog(*args, **kwargs):
            api._close()
            return (str(path),)

        api._window.create_file_dialog.side_effect = dialog
    else:
        write = gui.write_ports_json

        def writer(entries, stream):
            write(entries, stream)
            api._close()

        monkeypatch.setattr(gui, "write_ports_json", writer)
    assert api.export_ports(*args)["ok"] is False
    assert path.read_text() == "ORIGINAL"
    assert list(tmp_path.iterdir()) == [path]
    assert api._snapshot is None


def test_unexpected_action_errors_do_not_escape_or_reuse_consent(api):
    api._prepare = Mock(side_effect=RuntimeError("secret identity"))
    assert api.prepare_process(42) == {
        "ok": False,
        "code": "internal_error",
        "message": "Nie udało się wykonać operacji aplikacji.",
    }
    target = KillTarget(42, 1.5, "test", "/test", ("test",))
    api._prepare = lambda pid: target
    api._terminate = Mock(side_effect=RuntimeError("secret signal detail"))
    prepared = api.prepare_process(42)
    assert prepared["ok"]
    assert api.terminate_process(prepared["token"])["code"] == "internal_error"
    assert api.terminate_process(prepared["token"])["code"] == "consent_expired"
    assert not api._action_lock.locked()


def test_shutdown_during_admitted_termination_retains_no_escalation(api):
    target = KillTarget(42, 1.5, "test", "/test", ("test",))
    api._prepare = lambda pid: target

    def terminate(*args, **kwargs):
        api._close()
        raise TerminationPending(target)

    api._terminate = terminate
    prepared = api.prepare_process(42)
    result = api.terminate_process(prepared["token"])
    assert result["ok"] is False
    assert "continuation" not in result
    assert not api._targets
    assert api._expiry_timer is None


def test_unexpected_metadata_error_is_safe(api, monkeypatch):
    monkeypatch.setattr(gui, "version", Mock(side_effect=RuntimeError("private path")))
    assert api.get_app_info()["code"] == "internal_error"
