"""Process-table traversal must stay linear and never follow reused identities."""

from unittest.mock import MagicMock, Mock

import psutil
import pytest

from portscanner.core import command


def process(pid, parent, created):
    """Build a process with a stable, explicitly controlled lifetime identity."""
    result = MagicMock(pid=pid)
    result.ppid.return_value = parent
    result.create_time.return_value = created
    return result


@pytest.fixture
def table(monkeypatch):
    """Expose fresh current identities separately from objects retained by callers."""
    current = {}

    def lookup(pid):
        if pid not in current:
            raise psutil.NoSuchProcess(pid)
        return current[pid]

    scan = Mock(side_effect=lambda: list(reversed(current)))
    monkeypatch.setattr(command.psutil, "pids", scan)
    monkeypatch.setattr(command.psutil, "Process", lookup)
    return current, scan


@pytest.mark.parametrize("count", [0, 1, 20])
def test_one_scan_discovers_entire_tree(table, count):
    """The number of process-table scans cannot grow with the descendant count."""
    current, scan = table
    root = current[1] = process(1, 0, 1)
    for pid in range(2, count + 2):
        current[pid] = process(pid, pid - 1, pid)
    descendants = {}
    command._observe_descendants(root, descendants)
    assert set(descendants) == set(range(2, count + 2))
    scan.assert_called_once_with()
    for item in current.values():
        item.children.assert_not_called()
    command._observe_descendants(root, descendants)
    assert scan.call_count == 2


def test_reparented_descendant_remains_an_anchor(table):
    """An observed child can reveal new descendants after its original root exits."""
    current, _ = table
    root = process(1, 0, 1)
    child = current[2] = process(2, 999, 2)
    current[3] = process(3, 2, 3)
    descendants = {2: child}
    command._observe_descendants(root, descendants)
    assert set(descendants) == {2, 3}
    command._stop_descendants(descendants)
    child.kill.assert_called_once()
    current[3].kill.assert_called_once()


@pytest.mark.parametrize("reused_pid", [1, 2])
def test_reused_ancestor_cannot_adopt_unrelated_children(table, reused_pid):
    """A root or retained child's PID reuse must not expand the tracked tree."""
    current, _ = table
    root, old_child = process(1, 0, 1), process(2, 1, 2)
    current[reused_pid] = process(reused_pid, 999, 100)
    current[3] = process(3, reused_pid, 101)
    descendants = {2: old_child}
    command._observe_descendants(root, descendants)
    assert descendants == {2: old_child}
    command._stop_descendants(descendants)
    old_child.kill.assert_not_called()
    for item in current.values():
        item.kill.assert_not_called()


def test_child_identity_is_rechecked_after_snapshot(table, monkeypatch):
    """PID reuse between enumeration and adoption must not reach cleanup."""
    current, _ = table
    root = current[1] = process(1, 0, 1)
    child = current[2] = process(2, 1, 2)
    replacement = process(2, 999, 100)
    reads = 0

    def lookup(pid):
        nonlocal reads
        if pid == 2:
            reads += 1
            return child if reads == 1 else replacement
        return current[pid]

    monkeypatch.setattr(command.psutil, "Process", lookup)
    descendants = {}
    command._observe_descendants(root, descendants)
    assert descendants == {}


def test_child_older_than_parent_is_not_adopted(table):
    """A stale PPID edge must not connect a child to a newer parent lifetime."""
    current, _ = table
    root = current[1] = process(1, 0, 10)
    current[2] = process(2, 1, 2)
    descendants = {}
    command._observe_descendants(root, descendants)
    assert descendants == {}


def test_identity_is_rechecked_before_cleanup(table):
    """A tracked PID reused after observation must never receive kill."""
    current, _ = table
    old_child = process(2, 1, 2)
    current[2] = process(2, 999, 100)
    command._stop_descendants({2: old_child})
    old_child.kill.assert_not_called()
    current[2].kill.assert_not_called()
