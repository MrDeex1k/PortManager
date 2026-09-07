"""Interakcje headless; odczyty i sygnały procesów zastąpione kontrolowanym core."""

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from textual.widgets import Button, Checkbox, Static

from portscanner.core.actions import KillTarget, ProcessActionError
from portscanner.core.model import (
    DockerPort,
    LocalIP,
    PortEntry,
    ProcessInfo,
    Snapshot,
    SourceReport,
    TunnelRoute,
)
from portscanner.tui import PortScannerApp
from portscanner.tui import app as tui
from portscanner.tui.dialogs import KillScreen


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> Mock:
    snapshot = Snapshot(
        (
            PortEntry("tcp", "127.0.0.1", 8080, 42, ProcessInfo(42, "ok", "bun")),
            PortEntry("tcp", "127.0.0.1", 80, 43, ProcessInfo(43, "ok", "python")),
            PortEntry("udp", "::1", 5353),
        ),
        (LocalIP("lo", "127.0.0.1", "ipv4"),),
        (),
        (),
        (SourceReport("listeners", "ok"),),
    )
    mock = Mock(return_value=snapshot)
    monkeypatch.setattr(tui, "collect_snapshot", mock)
    monkeypatch.setattr(tui, "prepare_kill", Mock(side_effect=AssertionError("kill")))
    monkeypatch.setattr(
        tui, "terminate_target", Mock(side_effect=AssertionError("kill"))
    )
    return mock


async def wait_until(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not condition():
            await asyncio.sleep(0.01)


def test_start_filter_sort_and_quit(source: Mock) -> None:
    async def scenario() -> None:
        app = PortScannerApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await app.workers.wait_for_complete()
            assert [e.port for e in app.visible_entries] == [80, 5353, 8080]
            assert app.focused is app.table
            await pilot.press("s")
            assert [e.port for e in app.visible_entries] == [5353, 8080, 80]
            await pilot.press("/", ":", "8", "0", "enter")
            assert [e.port for e in app.visible_entries] == [80]
            assert app.focused is app.table
            await pilot.press("/", "ctrl+shift+a", "s", "r", "k", "j", "q", "/")
            assert app.filter_input.value == "srkjq/"
            assert app.is_running and app._sort_process
            assert not app._action_busy and not app._exporting
            await pilot.press("ctrl+shift+a", "backspace", "escape")
            assert app.table.row_count == 3
            await pilot.press("q")
            assert not app.is_running

    asyncio.run(scenario())


def test_refresh_updates_only_diff_and_preserves_identity(source: Mock) -> None:
    async def scenario() -> None:
        app = PortScannerApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app.table.move_cursor(row=2)
            selected = app._selected_key()
            add, remove, update = (
                Mock(wraps=app.table.add_row),
                Mock(wraps=app.table.remove_row),
                Mock(wraps=app.table.update_cell),
            )
            app.table.add_row, app.table.remove_row, app.table.update_cell = (
                add,
                remove,
                update,
            )
            await pilot.press("r")
            await app.workers.wait_for_complete()
            add.assert_not_called()
            remove.assert_not_called()
            update.assert_not_called()
            before = source.return_value
            changed = replace(before.ports[0], process=ProcessInfo(42, "ok", "deno"))
            # Wspólny bind/port, ale inny PID i pochodzenie: osobne wiersze.
            shared = replace(changed, pid=44, process=ProcessInfo(44, "ok", "node"))
            publication = replace(changed, origin="docker")
            source.return_value = replace(before, ports=(changed, shared, publication))
            await pilot.press("r")
            await app.workers.wait_for_complete()
            assert app._selected_key() == selected
            assert selected is not None
            assert app.table.row_count == 3
            assert add.call_count == 2 and remove.call_count == 2
            assert update.call_count == 1
            assert app.table.get_row(selected)[4].plain == "deno"
            source.return_value = replace(before, ports=())
            await pilot.press("r")
            await app.workers.wait_for_complete()
            assert not app.visible_entries

    asyncio.run(scenario())


def test_slow_scan_is_nonblocking_and_never_overlaps(source: Mock) -> None:
    entered, release = Event(), Event()
    snapshot = source.return_value

    def slow_read() -> Snapshot:
        entered.set()
        assert release.wait(5)
        return snapshot

    source.side_effect = slow_read

    async def scenario() -> None:
        app = PortScannerApp()
        try:
            async with app.run_test() as pilot:
                await wait_until(entered.is_set)
                await pilot.press("r", "r", "/", "p", "y")
                assert app.filter_input.value == "py"
                await pilot.pause(
                    2.1
                )  # Rzeczywisty tick set_interval, wciąż trwa odczyt.
                assert source.call_count == 1
                release.set()
                await app.workers.wait_for_complete()
                assert [e.pid for e in app.visible_entries] == [43]
                await wait_until(lambda: source.call_count >= 2)
        finally:
            release.set()

    asyncio.run(scenario())


def test_bad_filter_and_read_failure_are_visible_and_recover(source: Mock) -> None:
    snapshot = source.return_value
    source.return_value = replace(
        snapshot,
        reports=(SourceReport("listeners", "error", "Brak uprawnień [red]"),),
    )

    async def scenario() -> None:
        app = PortScannerApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            assert "Brak uprawnień [red]" in str(app.reports.content)
            await pilot.press("/", ":", "x", "escape", "j")
            assert not app.visible_entries
            assert app.filter_input.border_subtitle
            assert "poprawnego filtra" in str(app.message.content)
            await pilot.press("/", "ctrl+shift+a", "backspace", "escape")
            assert len(app.visible_entries) == 3
            assert app.filter_input.border_subtitle is None
            source.side_effect = RuntimeError("odczyt przerwany")
            await pilot.press("r")
            await app.workers.wait_for_complete()
            assert len(app.visible_entries) == 3
            assert "poprzednie dane" in str(app.reports.content)
            source.side_effect = None
            source.return_value = snapshot
            await pilot.press("r")
            await app.workers.wait_for_complete()
            assert str(app.reports.content) == ""

    asyncio.run(scenario())


def test_export_visible_order_and_full_model(source: Mock, tmp_path: Path) -> None:
    snapshot = source.return_value
    first = replace(
        snapshot.ports[0],
        docker=(DockerPort("abc", "web", "*", 8080, 80, "tcp", "demo", "web"),),
        tunnels=(TunnelRoute(50, "app.example.com", "localhost", 8080),),
        process=ProcessInfo(42, "ok", "[red]bun\x1b", ("bun", "app.js")),
    )
    source.return_value = replace(snapshot, ports=(first, snapshot.ports[1]))

    async def scenario() -> None:
        app = PortScannerApp(export_directory=tmp_path)
        async with app.run_test(size=(140, 32)) as pilot:
            await app.workers.wait_for_complete()
            cell = app.table.get_row(tui.row_key(first))[4]
            assert cell.plain == "[red]bun?" and not cell.spans
            await pilot.press("s", "j")
            await app.workers.wait_for_complete()
            files = list(tmp_path.glob("*.json"))
            assert len(files) == 1
            expected = json.loads(json.dumps([asdict(e) for e in app.visible_entries]))
            assert json.loads(files[0].read_text()) == expected
            assert [e["port"] for e in expected] == [8080, 80]
            if os.name == "posix":
                assert files[0].stat().st_mode & 0o777 == 0o600
            await pilot.press("/", ":", "8", "0", "escape", "j")
            await app.workers.wait_for_complete()
            newest = sorted(tmp_path.glob("*.json"))[-1]
            assert [e["port"] for e in json.loads(newest.read_text())] == [80]
            assert "Zapisano 1 wpisów" in str(app.message.content)

    asyncio.run(scenario())


def test_export_refuses_overwrite_and_symlink(
    source: Mock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Mock()
    clock.now.return_value = datetime(2026, 9, 7, 12)
    monkeypatch.setattr(tui, "datetime", clock)
    path = tui.export_json(source.return_value.ports, tmp_path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        tui.export_json((), tmp_path)
    assert path.read_bytes() == original
    if os.name == "posix":
        target = tmp_path / "target.json"
        target.write_text("existing")
        path.unlink()
        path.symlink_to(target)
        with pytest.raises(FileExistsError):
            tui.export_json((), tmp_path)
        assert target.read_text() == "existing"


def test_export_failure_keeps_app_usable(source: Mock, tmp_path: Path) -> None:
    async def scenario() -> None:
        app = PortScannerApp(export_directory=tmp_path / "missing")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("j")
            await app.workers.wait_for_complete()
            assert "Eksport nie powiódł się" in str(app.message.content)
            await pilot.press("q")
            assert not app.is_running

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_key", ["escape", "enter"])
def test_kill_cancel_and_default_focus_never_signal(
    source: Mock, monkeypatch: pytest.MonkeyPatch, cancel_key: str
) -> None:
    target = KillTarget(43, 100.0, "python", "/bin/python", ("python", "server.py"))
    prepare, terminate = Mock(return_value=target), Mock()
    monkeypatch.setattr(tui, "prepare_kill", prepare)
    monkeypatch.setattr(tui, "terminate_target", terminate)

    async def scenario() -> None:
        app = PortScannerApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("k")
            await wait_until(lambda: isinstance(app.screen, KillScreen))
            await pilot.pause()
            assert isinstance(app.focused, Button) and app.focused.id == "cancel"
            assert not app.screen.query_one(Checkbox).value
            await pilot.press("q", "j", "k")
            assert isinstance(app.screen, KillScreen)
            await pilot.press(cancel_key)
            await app.workers.wait_for_complete()
            assert not isinstance(app.screen, KillScreen)
            assert "Anulowano" in str(app.message.content)
            prepare.assert_called_once_with(43)
            terminate.assert_not_called()

    asyncio.run(scenario())


@pytest.mark.parametrize("force", [False, True])
def test_kill_confirms_captured_identity_despite_refresh(
    source: Mock, monkeypatch: pytest.MonkeyPatch, force: bool
) -> None:
    target = KillTarget(
        43,
        100.0,
        "python",
        "/bin/python",
        ("python", "server.py", "--password=private-value"),
    )
    prepare, terminate = Mock(return_value=target), Mock()
    monkeypatch.setattr(tui, "prepare_kill", prepare)
    monkeypatch.setattr(tui, "terminate_target", terminate)

    async def scenario() -> None:
        app = PortScannerApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("k")
            await wait_until(lambda: isinstance(app.screen, KillScreen))
            await pilot.pause()
            details = "\n".join(
                str(widget.content) for widget in app.screen.query(Static)
            )
            assert "private-value" not in details and "--password=***" in details
            source.return_value = replace(source.return_value, ports=())
            app.action_refresh()
            await wait_until(lambda: not app._refreshing)
            assert not app.visible_entries
            if force:
                await pilot.click("#force")
            await pilot.click("#confirm")
            await app.workers.wait_for_complete()
            terminate.assert_called_once_with(target, force=force)
            assert "Zakończono proces PID 43" in str(app.message.content)

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["prepare", "terminate"])
def test_kill_policy_error_is_visible(
    source: Mock, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    target = KillTarget(43, 100.0, "python", "/bin/python", ("python",))
    prepare, terminate = Mock(return_value=target), Mock()
    (prepare if stage == "prepare" else terminate).side_effect = ProcessActionError(
        "Odmowa: proces zmienił tożsamość."
    )
    monkeypatch.setattr(tui, "prepare_kill", prepare)
    monkeypatch.setattr(tui, "terminate_target", terminate)

    async def scenario() -> None:
        app = PortScannerApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("k")
            if stage == "terminate":
                await wait_until(lambda: isinstance(app.screen, KillScreen))
                await pilot.pause()
                await pilot.click("#confirm")
            await app.workers.wait_for_complete()
            assert "zmienił tożsamość" in str(app.message.content)
            assert not app._action_busy
            if stage == "prepare":
                terminate.assert_not_called()
            await pilot.press("q")
            assert not app.is_running

    asyncio.run(scenario())


def test_slow_termination_does_not_block_or_repeat(
    source: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = KillTarget(43, 100.0, "python", "/bin/python", ("python",))
    entered, release = Event(), Event()

    def slow_terminate(*args: object, **kwargs: object) -> None:
        entered.set()
        assert release.wait(5)

    terminate = Mock(side_effect=slow_terminate)
    monkeypatch.setattr(tui, "prepare_kill", Mock(return_value=target))
    monkeypatch.setattr(tui, "terminate_target", terminate)

    async def scenario() -> None:
        app = PortScannerApp()
        try:
            async with app.run_test(size=(80, 24)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.press("k")
                await wait_until(lambda: isinstance(app.screen, KillScreen))
                await pilot.pause()
                assert await pilot.click("#confirm")
                await wait_until(entered.is_set)
                await pilot.press("k", "q", "/", "p", "y", "escape", "s")
                assert app.is_running and app._sort_process
                assert app.filter_input.value == "py"
                assert "Poczekaj" in str(app.message.content)
                terminate.assert_called_once_with(target, force=False)
                release.set()
                await app.workers.wait_for_complete()
                await pilot.press("q")
                assert not app.is_running
        finally:
            release.set()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["empty", "unknown", "docker"])
def test_kill_requires_socket_with_pid(
    source: Mock, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    entry = PortEntry("tcp", "*", 80, 43 if kind == "docker" else None)
    if kind == "docker":
        entry = replace(entry, origin="docker")
    source.return_value = replace(
        source.return_value, ports=() if kind == "empty" else (entry,)
    )
    prepare = Mock()
    monkeypatch.setattr(tui, "prepare_kill", prepare)

    async def scenario() -> None:
        app = PortScannerApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("k")
            prepare.assert_not_called()
            assert str(app.message.content)

    asyncio.run(scenario())
