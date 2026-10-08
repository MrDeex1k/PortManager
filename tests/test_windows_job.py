"""Job Object i bramka startowa; integracja Win32 uruchamia się na Windows."""

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from portscanner.core import kube_command as command
from portscanner.core import windows_job


def test_job_tracks_processes_independently_of_parent_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = Mock()
    kernel.CreateJobObjectW.return_value = 0x100000001
    kernel.OpenProcess.return_value = 0x100000002
    kernel.SetInformationJobObject.return_value = 1
    kernel.AssignProcessToJobObject.return_value = 1
    kernel.CloseHandle.return_value = 1
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=kernel), raising=False)
    job = windows_job.WindowsJob(42)
    limits = kernel.SetInformationJobObject.call_args.args
    info = ctypes.cast(limits[2], ctypes.POINTER(windows_job._ExtendedLimits)).contents
    assert info.BasicLimitInformation.LimitFlags == 0x2000
    kernel.AssignProcessToJobObject.assert_called_once_with(0x100000001, 0x100000002)
    process = Mock(pid=42, returncode=0)
    monkeypatch.setattr(command, "os", SimpleNamespace(name="nt"))
    command._stop_tree(process, job)
    job.close()  # idempotent
    assert kernel.CloseHandle.call_count == 2  # process handle, then job
    process.wait.assert_called_once()
    process.kill.assert_not_called()


def test_windows_job_assignment_failure_never_releases_kubectl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock(pid=42)
    monkeypatch.setattr(command, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(command.shutil, "which", Mock(return_value="kubectl.exe"))
    monkeypatch.setattr(command.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(command, "WindowsJob", Mock(side_effect=OSError("Job failure")))
    with pytest.raises(OSError, match="Job failure"):
        command._start(["kubectl", "get", "nodes"])
    process.stdin.write.assert_not_called()
    process.kill.assert_called_once()
    process.wait.assert_called_once()
    for stream in (process.stdin, process.stdout, process.stderr):
        stream.close.assert_called_once()


def test_gate_waits_for_assignment_and_closes_kubectl_stdin(tmp_path: Path) -> None:
    marker = tmp_path / "started"
    script = (
        f"from pathlib import Path; import sys; Path({str(marker)!r}).touch(); "
        "assert sys.stdin.read() == ''; print('ok')"
    )
    with subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-u",
            "-c",
            command._WINDOWS_GATE,
            sys.executable,
            "-c",
            script,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        assert not marker.exists()
        stdout, stderr = process.communicate(b"1", timeout=3)
        assert process.returncode == 0, stderr
        assert stdout.strip() == b"ok" and marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows Job Object")
@pytest.mark.parametrize("ending", ["success", "timeout", "limit"])
def test_native_job_cleans_orphaned_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    pid_file = tmp_path / "plugin.pid"
    finish = {
        "success": "print('{}')",
        "timeout": "time.sleep(10)",
        "limit": (
            "sys.stdout.buffer.write(b'x'*65536); sys.stdout.flush(); time.sleep(10)"
        ),
    }[ending]
    script = f"""import subprocess, sys, time
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
open({str(pid_file)!r}, 'w').write(str(p.pid))
{finish}
"""
    real_start = command._start
    monkeypatch.setattr(
        command, "_start", lambda args: real_start([sys.executable, "-c", script])
    )
    monkeypatch.setattr(command, "OUTPUT_LIMIT", 32768)
    try:
        if ending == "success":
            assert command.run_kubectl("services,nodes", 3).strip() == "{}"
        else:
            with pytest.raises(
                subprocess.TimeoutExpired if ending == "timeout" else ValueError
            ):
                command.run_kubectl("services,nodes", 2)
        if pid_file.exists():
            try:
                child = psutil.Process(int(pid_file.read_text()))
                deadline = time.monotonic() + 2
                while child.is_running():
                    assert time.monotonic() < deadline, "Plugin survived job closure"
                    time.sleep(0.02)
            except psutil.NoSuchProcess:
                pass
        else:
            pytest.fail("The fake plugin never started")
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
