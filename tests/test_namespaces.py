from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from portscanner.core import namespaces


@pytest.mark.parametrize("inodes,expected", [([1, 1, 2, 2], True), ([1, 9], False)])
def test_linux_compares_namespace_inodes(
    monkeypatch: pytest.MonkeyPatch,
    inodes: list[int],
    expected: bool,
) -> None:
    monkeypatch.setattr(namespaces, "sys", SimpleNamespace(platform="linux"))
    stat = Mock(side_effect=[SimpleNamespace(st_ino=n) for n in inodes])
    monkeypatch.setattr(Path, "stat", stat)
    assert namespaces.same_namespaces(42) is expected
    assert stat.call_count == len(inodes)


def test_namespace_read_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(namespaces, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(Path, "stat", Mock(side_effect=PermissionError()))
    with pytest.raises(PermissionError):
        namespaces.same_namespaces(42)


def test_other_platforms_do_not_read_proc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(namespaces, "sys", SimpleNamespace(platform="darwin"))
    stat = Mock(side_effect=AssertionError("Nie czytaj /proc"))
    monkeypatch.setattr(Path, "stat", stat)
    assert namespaces.same_namespaces(42)
    stat.assert_not_called()
