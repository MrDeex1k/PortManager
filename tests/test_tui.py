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
from textual.containers import VerticalScroll
from textual.widgets import Button, Checkbox, Static

from portscanner.core.actions import KillTarget, ProcessActionError
from portscanner.core.model import (
    DockerPort,
    LocalIP,
    PortEntry,
    ProcessInfo,
    Snapshot,
    SourceReport,
    TunnelInfo,
    TunnelRoute,
)
from portscanner.tui import PortScannerApp
from portscanner.tui import app as tui
from portscanner.tui.dialogs import DiagnosticsScreen, KillScreen


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

    def slow_read(*, kube: bool = False, kube_discovery: object = None) -> Snapshot:
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


@pytest.mark.parametrize("platform", ["posix", "nt"])
@pytest.mark.parametrize("cancel_key", ["escape", "enter"])
def test_kill_cancel_and_default_focus_never_signal(
    source: Mock, monkeypatch: pytest.MonkeyPatch, cancel_key: str, platform: str
) -> None:
    """Cancellation never signals a process on either platform's dialog layout."""
    from types import SimpleNamespace

    from portscanner.tui import dialogs

    monkeypatch.setattr(dialogs, "os", SimpleNamespace(name=platform))
    target = KillTarget(43, 100.0, "python", "/bin/python", ("python", "server.py"))
    prepare, terminate = Mock(return_value=target), Mock()
    monkeypatch.setattr(tui, "prepare_kill", prepare)
    monkeypatch.setattr(tui, "terminate_target", terminate)

    async def scenario() -> None:
        """Check focus and platform controls, then cancel without a signal."""
        app = PortScannerApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("k")
            await wait_until(lambda: isinstance(app.screen, KillScreen))
            await pilot.pause()
            assert isinstance(app.focused, Button) and app.focused.id == "cancel"
            if platform == "posix":
                assert not app.screen.query_one(Checkbox).value
            else:
                assert not list(app.screen.query(Checkbox))
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
    """Confirmation uses the captured identity even when refresh removes its row."""
    from types import SimpleNamespace

    from portscanner.tui import dialogs

    monkeypatch.setattr(dialogs, "os", SimpleNamespace(name="posix"))
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


def test_kube_is_forwarded_to_worker(source: Mock) -> None:
    async def scenario() -> None:
        app = PortScannerApp(kube=True)
        async with app.run_test():
            await app.workers.wait_for_complete()
            source.assert_called_with(kube=True, kube_discovery=app._kube_discovery)

    asyncio.run(scenario())


@pytest.mark.parametrize("confirm", [False, True])
def test_timeout_opens_new_consent_after_port_disappears(source, monkeypatch, confirm):
    """Timeout requires new consent even after the target row disappears."""
    from portscanner.core.actions import TerminationPending

    target = KillTarget(43, 100.0, "python", "/bin/python", ("python", "server.py"))
    pending = TerminationPending(target)
    resume = Mock(return_value="terminated")
    monkeypatch.setattr(pending.pending, "resume", resume)
    monkeypatch.setattr(tui, "prepare_kill", Mock(return_value=target))
    monkeypatch.setattr(tui, "terminate_target", Mock(side_effect=pending))

    async def scenario():
        """Keep continuation idle until the second dialog is explicitly answered."""
        app = PortScannerApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("k")
            await wait_until(lambda: isinstance(app.screen, KillScreen))
            await pilot.pause()
            await pilot.click("#confirm")
            await wait_until(
                lambda: isinstance(app.screen, KillScreen) and app.screen.escalation
            )
            source.return_value = replace(source.return_value, ports=())
            app.action_refresh()
            await wait_until(lambda: not app._refreshing)
            await pilot.pause()
            resume.assert_not_called()
            assert app.screen.focused is not None and app.screen.focused.id == "cancel"
            await pilot.click("#confirm" if confirm else "#cancel")
            await app.workers.wait_for_complete()
            assert resume.call_count == int(confirm)

    asyncio.run(scenario())


def test_windows_dialog_explains_hard_termination(source, monkeypatch):
    """Windows consent explains hard termination and offers no force checkbox."""
    from types import SimpleNamespace

    from portscanner.tui import dialogs

    monkeypatch.setattr(dialogs, "os", SimpleNamespace(name="nt"))
    target = KillTarget(43, 100.0, "python", "C:/python.exe", ("python", "server.py"))
    monkeypatch.setattr(tui, "prepare_kill", Mock(return_value=target))

    async def scenario():
        """Inspect the Windows dialog and cancel without terminating the target."""
        app = PortScannerApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("k")
            await wait_until(lambda: isinstance(app.screen, KillScreen))
            await pilot.pause()
            assert not list(app.screen.query("#force"))
            assert any(
                "twarde zakończenie" in str(widget.content)
                for widget in app.screen.query(Static)
            )
            await pilot.click("#cancel")
            await app.workers.wait_for_complete()

    asyncio.run(scenario())


def test_reports_and_local_ips_scroll_with_keyboard(source):
    """Capped panels must retain all content and offer keyboard scrolling."""
    source.return_value = replace(
        source.return_value,
        local_ips=tuple(
            LocalIP(f"interface-{i}", f"192.0.2.{i}", "ipv4") for i in range(1, 25)
        ),
        reports=tuple(
            SourceReport(name, "error", "message " * 25, code="timeout")
            for name in ("listeners", "processes", "local_ips", "docker", "tunnels")
        ),
    )

    async def scenario():
        """Reach panel overflow and the full diagnostic view using keyboard actions."""
        app = PortScannerApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            for panel_id in ("#summary-panel", "#reports-panel"):
                panel = app.query_one(panel_id, VerticalScroll)
                assert panel.max_scroll_y > 0
                panel.focus()
                await pilot.press("end")
                await pilot.pause()
                assert panel.scroll_y > 0
            assert "[timeout]" in str(app.reports.content)
            await pilot.press("escape", "d")
            assert isinstance(app.screen, DiagnosticsScreen)
            scroll = app.screen.query_one("#diagnostics-scroll", VerticalScroll)
            assert app.screen.focused is scroll
            await pilot.press("end")
            await pilot.pause()
            assert scroll.scroll_y > 0
            await pilot.press("escape")
            assert not isinstance(app.screen, DiagnosticsScreen)

    asyncio.run(scenario())


def test_standalone_connector_and_reason_codes_survive_empty_filter(source):
    """Connector health remains visible even without any matching port row."""
    source.return_value = replace(
        source.return_value,
        tunnels=(
            TunnelInfo(
                998877, config_status="remote", metrics_status="ok", connections=0
            ),
            TunnelInfo(
                998878,
                config_status="error",
                config_code="unsafe_file",
                metrics_status="error",
                metrics_code="timeout",
            ),
        ),
    )

    async def scenario():
        """Filter away every port while retaining connector state in both views."""
        app = PortScannerApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("/", "z", "z", "escape")
            assert app.visible_entries == ()
            details = str(app.tunnels.content)
            assert "PID 998877" in details and "połączenia=0" in details
            assert "unsafe_file" in details and "timeout" in details
            assert app.query_one("#tunnels-panel").display
            await pilot.press("d")
            assert isinstance(app.screen, DiagnosticsScreen)
            assert "unsafe_file" in " ".join(
                str(w.content) for w in app.screen.query(Static)
            )
            await pilot.press("escape")

    asyncio.run(scenario())


def test_explicit_refreshes_coalesce_and_reach_kubernetes(source, monkeypatch):
    """A busy scan must retain manual refresh intent without overlapping reads."""
    entered, release = Event(), Event()
    old = source.return_value
    new = replace(old, ports=())

    def first_read(**kwargs):
        """Hold the initial read until explicit refresh requests have arrived."""
        entered.set()
        assert release.wait(5)
        return old

    calls = 0

    def scan(**kwargs):
        """Return the new snapshot only after the initial read is released."""
        nonlocal calls
        calls += 1
        return first_read(**kwargs) if calls == 1 else new

    source.side_effect = scan

    async def scenario():
        """Queue two manual requests and verify one subsequent scan consumes them."""
        app = PortScannerApp(kube=True)
        request = Mock(wraps=app._kube_discovery.request_refresh)
        monkeypatch.setattr(app._kube_discovery, "request_refresh", request)
        try:
            async with app.run_test() as pilot:
                await wait_until(entered.is_set)
                await pilot.press("r", "r")
                assert source.call_count == 1
                assert request.call_count == 3  # Initial read and two manual requests.
                assert app._refresh_pending
                app._periodic_refresh()
                assert request.call_count == 3
                release.set()
                await app.workers.wait_for_complete()
                assert source.call_count == 2
                assert app.snapshot is new and app.visible_entries == ()
        finally:
            release.set()

    asyncio.run(scenario())


def test_kill_during_scan_discards_old_result_and_refreshes(source, monkeypatch):
    """A pre-termination scan cannot republish the killed process after success."""
    entered, release = Event(), Event()
    old = source.return_value
    new = replace(old, ports=())
    calls = 0

    def scan(**kwargs):
        """Delay the second read to deliver a stale pre-termination snapshot."""
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            assert release.wait(5)
        return old if calls <= 2 else new

    source.side_effect = scan
    target = KillTarget(43, 100.0, "python", "/bin/python", ("python",))
    monkeypatch.setattr(tui, "prepare_kill", Mock(return_value=target))
    terminate = Mock(return_value="terminated")
    monkeypatch.setattr(tui, "terminate_target", terminate)

    async def scenario():
        """Confirm a simulated kill while reading, then require a fresh empty result."""
        app = PortScannerApp()
        try:
            async with app.run_test(size=(100, 32)) as pilot:
                await app.workers.wait_for_complete()
                app.action_refresh(force_kube=False)
                await wait_until(entered.is_set)
                await pilot.press("k")
                await wait_until(lambda: isinstance(app.screen, KillScreen))
                await pilot.pause()
                await pilot.click("#confirm")
                await wait_until(lambda: not app._action_busy)
                assert source.call_count == 2 and app._refresh_pending
                release.set()
                await app.workers.wait_for_complete()
                terminate.assert_called_once()
                assert source.call_count == 3
                assert app.snapshot is new and app.visible_entries == ()
        finally:
            release.set()

    asyncio.run(scenario())


@pytest.mark.parametrize("busy", [None, "_action_busy", "_exporting"])
def test_ctrl_q_works_in_filter_but_waits_for_active_operations(source, busy):
    """Global quit bypasses text-entry suppression, never operation safeguards."""

    async def scenario():
        """Exercise global quit with and without a pending mutation or export."""
        app = PortScannerApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("/")
            if busy:
                setattr(app, busy, True)
            await pilot.press("ctrl+q")
            assert app.is_running == bool(busy)
            if busy:
                assert "Poczekaj" in str(app.message.content)
                setattr(app, busy, False)
                await pilot.press("ctrl+q")
                assert not app.is_running

    asyncio.run(scenario())


def test_unchanged_rows_are_not_formatted_again(source, monkeypatch):
    """Diff-only rendering must skip cell formatting as well as widget writes."""

    async def scenario():
        """Count formatting for an unchanged snapshot and a single changed process."""
        app = PortScannerApp()
        async with app.run_test():
            await app.workers.wait_for_complete()
            cells = Mock(wraps=tui.entry_cells)
            monkeypatch.setattr(tui, "entry_cells", cells)
            app._render_rows()
            cells.assert_not_called()
            assert app.snapshot is not None
            changed = replace(
                app.snapshot.ports[0], process=ProcessInfo(42, "ok", "new-name")
            )
            app.snapshot = replace(
                app.snapshot, ports=(changed, *app.snapshot.ports[1:])
            )
            app._render_rows()
            assert cells.call_count == 2  # Old/new cells for the changed row only.

    asyncio.run(scenario())


def test_streaming_export_cleans_up_after_write_failure(tmp_path, monkeypatch):
    """Streaming failure must not leave a partial export or remove other files."""
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep")

    def fail(entries, stream):
        stream.write("[")
        raise OSError("disk full")

    monkeypatch.setattr(tui, "write_ports_json", fail)
    with pytest.raises(OSError, match="disk full"):
        tui.export_json((), tmp_path)
    assert list(tmp_path.glob("*.json")) == []
    assert unrelated.read_text() == "keep"


def test_quit_during_scan_does_not_start_pending_refresh(source):
    """A queued manual request must not restart discovery after the user exits."""
    entered, release = Event(), Event()
    snapshot = source.return_value

    def scan(**kwargs):
        entered.set()
        assert release.wait(5)
        return snapshot

    source.side_effect = scan

    async def scenario():
        """Exit with a queued request, release the read, and check no restart occurs."""
        app = PortScannerApp()
        try:
            async with app.run_test() as pilot:
                await wait_until(entered.is_set)
                await pilot.press("r")
                assert app._refresh_pending
                await app.action_quit_global()
                release.set()
        finally:
            release.set()
        assert source.call_count == 1

    asyncio.run(scenario())
