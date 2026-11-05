"""Zakończenie wyłącznie tymczasowego procesu utworzonego przez ten test."""

import subprocess
import sys

from portscanner.core.actions import prepare_kill, terminate_target


def test_terminate_own_temporary_listener() -> None:
    script = (
        "import socket, sys\n"
        "with socket.socket() as server:\n"
        "    server.bind(('127.0.0.1', 0))\n"
        "    server.listen()\n"
        "    print(server.getsockname()[1], flush=True)\n"
        "    sys.stdin.read()\n"
    )
    with subprocess.Popen(
        [sys.executable, "-u", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as child:
        try:
            assert child.stdout is not None
            assert child.stdout.readline().strip().isdigit()
            target = prepare_kill(child.pid)
            terminate_target(target, timeout=2.0)
            child.wait(timeout=2.0)
            assert child.poll() is not None
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2.0)


def test_resume_own_listener_after_it_closes_port():
    """Fresh consent can kill an owned process after SIGTERM has closed its listener."""
    import os

    import pytest

    from portscanner.core.actions import TerminationPending

    if os.name == "nt":
        pytest.skip("Windows terminate does not deliver a catchable SIGTERM")
    script = """import socket, signal, sys
server = socket.socket()
server.bind(('127.0.0.1', 0))
server.listen()
def drain(signum, frame):
    server.close()
signal.signal(signal.SIGTERM, drain)
print('READY', flush=True)
sys.stdin.read()
"""
    with subprocess.Popen(
        [sys.executable, "-u", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as child:
        try:
            assert child.stdout is not None
            assert child.stdout.readline().strip() == "READY"
            target = prepare_kill(child.pid)
            with pytest.raises(TerminationPending) as error:
                terminate_target(target, timeout=0.1)
            assert child.poll() is None
            assert error.value.pending.resume(timeout=2) == "terminated"
            assert child.wait(timeout=2) is not None
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)
