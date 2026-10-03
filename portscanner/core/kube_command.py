"""Ograniczony odczyt kubectl i sprzątanie procesów uwierzytelniania."""

import os
import queue
import signal
import subprocess
import threading
import time
from typing import BinaryIO

import psutil

OUTPUT_LIMIT = 4 * 1024 * 1024


def _stop_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        # Osobna sesja obejmuje również pluginy exec i ich potomków.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            parent.kill()
            psutil.wait_procs(children, timeout=1)
        except psutil.NoSuchProcess:
            pass
    process.wait()


def run_kubectl(resource: str, timeout: float) -> str:
    """Limit stdout + stderr łącznie, egzekwowany przed dekodowaniem JSON."""
    command = [
        "kubectl",
        "get",
        resource,
        "--all-namespaces",
        "--output=json",
        f"--request-timeout={timeout:.3f}s",
    ]
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    chunks: queue.Queue[tuple[bool, bytes | None]] = queue.Queue(maxsize=16)
    stop = threading.Event()

    def read(stream: BinaryIO, stdout: bool) -> None:
        try:
            while not stop.is_set():
                data = os.read(stream.fileno(), 8192)
                while not stop.is_set():
                    try:
                        chunks.put((stdout, data or None), timeout=0.05)
                        break
                    except queue.Full:
                        pass
                if not data:
                    break
        finally:
            stream.close()

    assert process.stdout is not None and process.stderr is not None
    readers = [
        threading.Thread(target=read, args=(process.stdout, True), daemon=True),
        threading.Thread(target=read, args=(process.stderr, False), daemon=True),
    ]
    output = bytearray()
    total = 0
    remaining_streams = 2
    try:
        for reader in readers:
            reader.start()
        while remaining_streams:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("kubectl", timeout)
            try:
                stdout, data = chunks.get(timeout=remaining)
            except queue.Empty as error:
                raise subprocess.TimeoutExpired("kubectl", timeout) from error
            if data is None:
                remaining_streams -= 1
                continue
            total += len(data)
            if total > OUTPUT_LIMIT:
                raise ValueError("Zbyt duża odpowiedź Kubernetes")
            if stdout:
                output.extend(data)
        code = process.wait(timeout=max(0, deadline - time.monotonic()))
        if code:
            # Stderr może zawierać poświadczenia; nie utrwalamy go w wyjątku.
            raise subprocess.CalledProcessError(code, "kubectl")
        return output.decode("utf-8")
    finally:
        stop.set()
        _stop_tree(process)
        for reader in readers:
            if reader.ident is not None:
                reader.join(timeout=1)
