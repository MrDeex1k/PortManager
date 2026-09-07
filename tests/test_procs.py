"""Proces może zniknąć lub udostępnić tylko część szczegółów."""

import json
import os
from dataclasses import asdict
from unittest.mock import Mock

import psutil
import pytest

from portscanner.core.model import PortEntry, ProcessInfo
from portscanner.core.procs import enrich_processes, read_process


@pytest.fixture
def process_factory(monkeypatch: pytest.MonkeyPatch) -> Mock:
    process = Mock()
    process.name.return_value = "python"
    process.cmdline.return_value = ["python", "my script.py", "--name", "a b"]
    process.is_running.return_value = True
    factory = Mock(return_value=process)
    monkeypatch.setattr(psutil, "Process", factory)
    return factory


def test_unknown_pid_does_not_read_own_process(process_factory: Mock) -> None:
    assert read_process(None) == ProcessInfo(None, "unknown")
    process_factory.assert_not_called()


@pytest.mark.parametrize("pid", [-1, True])
def test_invalid_pid_is_rejected(process_factory: Mock, pid: int) -> None:
    with pytest.raises(ValueError):
        read_process(pid)
    process_factory.assert_not_called()


def test_keeps_argument_boundaries_and_empty_cmdline(process_factory: Mock) -> None:
    assert read_process(42) == ProcessInfo(
        42, "ok", "python", ("python", "my script.py", "--name", "a b")
    )
    process_factory.return_value.cmdline.return_value = []
    assert read_process(42).cmdline == ()


@pytest.mark.parametrize("field", ["name", "cmdline"])
def test_access_denied_preserves_other_field(process_factory: Mock, field: str) -> None:
    getattr(process_factory.return_value, field).side_effect = psutil.AccessDenied(42)
    result = read_process(42)
    assert result.status == "access_denied"
    assert result.pid == 42
    assert getattr(result, field) is None
    assert getattr(result, "name" if field == "cmdline" else "cmdline") is not None


def test_both_fields_denied(process_factory: Mock) -> None:
    process_factory.return_value.name.side_effect = psutil.AccessDenied(42)
    process_factory.return_value.cmdline.side_effect = psutil.AccessDenied(42)
    assert read_process(42) == ProcessInfo(42, "access_denied")


@pytest.mark.parametrize(
    "error,status",
    [
        (psutil.AccessDenied(42), "access_denied"),
        (PermissionError("denied"), "access_denied"),
        (psutil.NoSuchProcess(42), "gone"),
        (psutil.ZombieProcess(42), "gone"),
        (OSError("failed"), "error"),
        (psutil.Error("failed"), "error"),
    ],
)
def test_constructor_errors_are_data(
    process_factory: Mock, error: Exception, status: str
) -> None:
    process_factory.side_effect = error
    result = read_process(42)
    assert result.status == status
    assert result.name is None and result.cmdline is None


@pytest.mark.parametrize("field", ["name", "cmdline", "is_running"])
def test_exit_during_read_discards_partial_data(
    process_factory: Mock, field: str
) -> None:
    getattr(process_factory.return_value, field).side_effect = psutil.NoSuchProcess(42)
    assert read_process(42) == ProcessInfo(42, "gone")


def test_reused_pid_during_read_discards_details(process_factory: Mock) -> None:
    process_factory.return_value.is_running.return_value = False
    assert read_process(42) == ProcessInfo(42, "gone")


def test_enrichment_preserves_entries_and_only_caches_one_snapshot(
    process_factory: Mock,
) -> None:
    entries = [
        PortEntry("tcp", "*", 80, 42),
        PortEntry("udp", "::1", 53, 42),
        PortEntry("tcp", "127.0.0.1", 8080),
    ]
    enriched = enrich_processes(iter(entries))
    process_factory.assert_called_once_with(42)
    assert all(entry.process is None for entry in entries)
    assert [(row.proto, row.bind, row.port, row.pid) for row in enriched] == [
        (row.proto, row.bind, row.port, row.pid) for row in entries
    ]
    assert enriched[0].process == enriched[1].process
    assert enriched[2].process == ProcessInfo(None, "unknown")
    assert json.loads(json.dumps(asdict(enriched[0])))["process"]["cmdline"] == [
        "python",
        "my script.py",
        "--name",
        "a b",
    ]
    process_factory.return_value.name.return_value = "changed"
    refreshed = enrich_processes(enriched)
    assert process_factory.call_count == 2
    assert refreshed[0].process is not None
    assert refreshed[0].process.name == "changed"


def test_one_inaccessible_pid_does_not_hide_other_ports(process_factory: Mock) -> None:
    process = process_factory.return_value
    process_factory.side_effect = [psutil.AccessDenied(42), process]
    result = enrich_processes(
        [
            PortEntry("tcp", "127.0.0.1", 80, 42),
            PortEntry("tcp", "127.0.0.1", 81, 43),
        ]
    )
    assert [row.process.status for row in result if row.process is not None] == [
        "access_denied",
        "ok",
    ]


def test_real_current_process() -> None:
    result = read_process(os.getpid())
    assert result.status == "ok"
    assert result.name
    assert result.cmdline
