"""Configuration I/O is size-limited and isolated from the snapshot process."""

import os
import subprocess
import time

import pytest

from portscanner.core import command


def test_regular_files_are_bounded(tmp_path):
    """Accept a regular file at the limit and reject oversized or absent files."""
    path = tmp_path / "config"
    path.write_bytes(b"1234")
    assert command.read_regular_file(str(path), timeout=2, limit=4) == b"1234"
    with pytest.raises(command.OutputLimitError):
        command.read_regular_file(str(path), timeout=2, limit=3)
    with pytest.raises(FileNotFoundError):
        command.read_regular_file(str(tmp_path / "missing"), timeout=2, limit=4)


@pytest.mark.skipif(os.name != "posix", reason="POSIX FIFO")
def test_fifo_without_writer_is_rejected_without_blocking(tmp_path):
    """Reject the descriptor type even when opening a FIFO through a symlink."""
    fifo, link = tmp_path / "fifo", tmp_path / "config.yml"
    os.mkfifo(fifo)
    link.symlink_to(fifo)
    start = time.monotonic()
    with pytest.raises(command.UnsafeFileError):
        command.read_regular_file(str(link), timeout=1, limit=1024)
    assert time.monotonic() - start < 1


def test_stalled_file_worker_is_killed(monkeypatch, tmp_path):
    """The caller can cancel even a reader stuck before returning any bytes."""
    monkeypatch.setattr(command, "_FILE_READER", "import time; time.sleep(10)")
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        command.read_regular_file(str(tmp_path / "config"), timeout=0.2, limit=1024)
    assert time.monotonic() - start < 1
