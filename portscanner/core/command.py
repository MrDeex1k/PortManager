"""Bounded CLI output and best-effort descendant cleanup without exposing stderr."""

import math
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from typing import BinaryIO

import psutil

from portscanner.core.windows_job import WindowsJob


class OutputLimitError(ValueError):
    """Combined stdout and stderr exceeded the permitted byte count."""


class UnsafeFileError(ValueError):
    """A configuration path did not refer to a regular file."""


def _same_process(process: psutil.Process) -> bool:
    """Compare a fresh identity against the creation time retained when observed."""
    try:
        return psutil.Process(process.pid).create_time() == process.create_time()
    except (psutil.Error, OSError, RuntimeError):
        return False


def _observe_descendants(
    root: psutil.Process, descendants: dict[int, psutil.Process]
) -> None:
    """Scan once, then traverse children of surviving, identity-checked ancestors."""
    current: dict[int, psutil.Process] = {}
    children: dict[int, list[psutil.Process]] = {}
    for pid in psutil.pids():
        try:
            process = psutil.Process(pid)  # Avoid process_iter's cached identities.
            with process.oneshot():
                parent_pid = process.ppid()
                process.create_time()  # Retain the identity before following edges.
            current[pid] = process
            children.setdefault(parent_pid, []).append(process)
        except (psutil.Error, OSError, RuntimeError):
            continue
    pending = [root, *descendants.values()]
    visited: set[int] = set()
    while pending:
        parent = pending.pop()
        if parent.pid in visited:
            continue
        actual = current.get(parent.pid)
        if actual is None or actual.create_time() != parent.create_time():
            continue
        if not _same_process(parent):
            continue
        visited.add(parent.pid)
        for child in children.get(parent.pid, ()):
            if child.create_time() < parent.create_time() or not _same_process(child):
                continue
            descendants[child.pid] = child
            pending.append(child)


def _stop_descendants(descendants: dict[int, psutil.Process]) -> None:
    """Never signal a PID that has been reused since it was observed."""
    for child in tuple(descendants.values()):
        try:
            if _same_process(child):
                child.kill()  # psutil also checks identity before signalling.
        except (psutil.Error, OSError, RuntimeError):
            pass


def _stop_tree(process: subprocess.Popen[bytes], job: WindowsJob | None = None) -> None:
    """Kill the original process group or Windows job and bound the reap wait."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
    elif job is not None:
        job.close()
    else:
        process.kill()
    process.wait(timeout=1)


_WINDOWS_GATE = """import subprocess, sys
if sys.stdin.buffer.read(1) != b'1':
    sys.exit(1)
try:
    code = subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL)
except OSError:
    sys.exit(127)
sys.exit(code)
"""


def _start(
    command: list[str], *, env: Mapping[str, str] | None = None
) -> tuple[subprocess.Popen[bytes], WindowsJob | None]:
    """Release a Windows child only after assigning its supervisor to a job."""
    if os.name != "nt":
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        ), None
    executable = shutil.which(command[0], path=env.get("PATH") if env else None)
    if executable is None:
        raise FileNotFoundError("Brak polecenia")
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-u",
            "-c",
            _WINDOWS_GATE,
            str(executable),
            *command[1:],
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    job = None
    try:
        job = WindowsJob(process.pid)
        assert process.stdin is not None
        process.stdin.write(b"1")
        process.stdin.close()
        return process, job
    except BaseException:
        try:
            _stop_tree(process, job)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        raise


def run_command(
    command: list[str],
    timeout: float,
    *,
    limit: int = 4 * 1024 * 1024,
    env: Mapping[str, str] | None = None,
    track_descendants: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """Return bounded stdout even on nonzero exit; discard stderr as it arrives.

    POSIX descendants observed while their parent lives are tracked by identity,
    including children in new sessions. Instant daemonization can evade polling;
    this is not OS containment. Pipe readers remain cancellable in that case.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatni i skończony")
    if type(limit) is not int or limit < 1:
        raise ValueError("Limit musi być dodatnią liczbą bajtów")
    deadline = time.monotonic() + timeout
    process, job = _start(command, env=env)
    chunks: queue.Queue[tuple[bool, bytes | None | Exception]] = queue.Queue(16)
    stop = threading.Event()
    descendants: dict[int, psutil.Process] = {}

    def watch() -> None:
        """Retain observed process identities even after reparenting or setsid."""
        try:
            root = psutil.Process(process.pid)
            root.create_time()
        except (psutil.Error, OSError, RuntimeError):
            return
        while not stop.is_set():
            try:
                _observe_descendants(root, descendants)
            except (psutil.Error, OSError, RuntimeError):
                pass
            stop.wait(0.01)

    def emit(stdout: bool, data: bytes | None | Exception) -> None:
        """Apply backpressure without preventing cancellation."""
        while not stop.is_set():
            try:
                chunks.put((stdout, data), timeout=0.02)
                return
            except queue.Full:
                pass

    def read(stream: BinaryIO, stdout: bool) -> None:
        """Read cancellably on POSIX, including pipes held by detached children."""
        try:
            if os.name == "posix":
                os.set_blocking(stream.fileno(), False)
            while not stop.is_set():
                try:
                    data = os.read(stream.fileno(), 8192)
                except BlockingIOError:
                    stop.wait(0.005)
                    continue
                emit(stdout, data or None)
                if not data:
                    break
        except OSError as error:
            emit(stdout, error)
        finally:
            stream.close()

    assert process.stdout is not None and process.stderr is not None
    readers = [
        threading.Thread(target=read, args=(process.stdout, True), daemon=True),
        threading.Thread(target=read, args=(process.stderr, False), daemon=True),
    ]
    watcher = (
        threading.Thread(target=watch, daemon=True)
        if os.name == "posix" and track_descendants
        else None
    )
    output = bytearray()
    total = 0
    streams = 2
    try:
        if watcher:
            watcher.start()
        for reader in readers:
            reader.start()
        while streams:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command[0], timeout)
            try:
                stdout, data = chunks.get(timeout=remaining)
            except queue.Empty as error:
                raise subprocess.TimeoutExpired(command[0], timeout) from error
            if isinstance(data, Exception):
                raise OSError("Odczyt polecenia niedostępny") from None
            if data is None:
                streams -= 1
                continue
            total += len(data)
            if total > limit:
                raise OutputLimitError("Zbyt duża odpowiedź polecenia")
            if stdout:
                output.extend(data)
        code = process.wait(timeout=max(0, deadline - time.monotonic()))
        return subprocess.CompletedProcess(command[0], code, bytes(output))
    finally:
        stop.set()
        if watcher and watcher.ident is not None:
            watcher.join(timeout=0.2)
        try:
            _stop_descendants(descendants)
            _stop_tree(process, job)
        finally:
            for reader in readers:
                if reader.ident is not None:
                    reader.join(timeout=0.2)


_FILE_READER = """import os, stat, sys
try:
    fd = os.open(sys.argv[1], os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            sys.exit(3)
        sys.stdout.buffer.write(f.read(int(sys.argv[2]) + 1))
except FileNotFoundError:
    sys.exit(4)
except OSError:
    sys.exit(5)
"""


def read_regular_file(path: str, *, timeout: float, limit: int) -> bytes:
    """Bound file I/O in a disposable process; reject FIFO/devices before reading."""
    result = run_command(
        [sys.executable, "-I", "-c", _FILE_READER, path, str(limit)],
        timeout,
        limit=limit,
        track_descendants=False,
    )
    if result.returncode == 3:
        raise UnsafeFileError("Konfiguracja nie jest zwykłym plikiem")
    if result.returncode == 4:
        raise FileNotFoundError()
    if result.returncode:
        raise OSError("Odczyt konfiguracji niedostępny")
    return result.stdout
