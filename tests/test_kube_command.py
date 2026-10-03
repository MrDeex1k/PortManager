"""Real subprocess regressions without a cluster or credentials."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from portscanner.core import kube_command as command

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")


def fake_kubectl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    executable = tmp_path / "kubectl"
    executable.write_text(f"#!{sys.executable}\n" + body)
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])


def test_success_and_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_kubectl(
        tmp_path,
        monkeypatch,
        """import sys,json
assert sys.argv[1:]==[
 'get','services,nodes','--all-namespaces','--output=json','--request-timeout=2.000s'
]
assert sys.stdin.read()==''
print(json.dumps({'items': []}))
""",
    )
    assert command.run_kubectl("services,nodes", 2).strip() == '{"items": []}'


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_limit_interrupts_writer_before_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stream: str,
) -> None:
    monkeypatch.setattr(command, "OUTPUT_LIMIT", 32768)
    fake_kubectl(
        tmp_path,
        monkeypatch,
        f"""import sys,time
for i in range(1000):
 sys.{stream}.buffer.write(b'x'*8192)
 sys.{stream}.flush()
time.sleep(10)
""",
    )
    start = time.monotonic()
    with pytest.raises(ValueError, match="Zbyt duża"):
        command.run_kubectl("services,nodes", 3)
    assert time.monotonic() - start < 2


def test_combined_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command, "OUTPUT_LIMIT", 32768)
    fake_kubectl(
        tmp_path,
        monkeypatch,
        """import sys
sys.stdout.buffer.write(b'x'*20000)
sys.stderr.buffer.write(b'y'*20000)
""",
    )
    with pytest.raises(ValueError):
        command.run_kubectl("services,nodes", 2)


@pytest.mark.parametrize("failure", ["timeout", "limit", "success"])
def test_cleans_plugin_descendants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(command, "OUTPUT_LIMIT", 32768)
    ending = {
        "timeout": "time.sleep(10)",
        "limit": (
            "sys.stdout.buffer.write(b'x'*65536); sys.stdout.flush(); time.sleep(10)"
        ),
        "success": "print('{}')",
    }[failure]
    fake_kubectl(
        tmp_path,
        monkeypatch,
        f"""import subprocess,sys,time
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'],
 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
open({str(pid_file)!r},'w').write(str(p.pid))
{ending}
""",
    )
    child = None
    try:
        if failure == "success":
            assert command.run_kubectl("services,nodes", 1).strip() == "{}"
        else:
            with pytest.raises(
                subprocess.TimeoutExpired if failure == "timeout" else ValueError
            ):
                command.run_kubectl("services,nodes", 1)
        child = psutil.Process(int(pid_file.read_text()))
        deadline = time.monotonic() + 2
        while child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
            assert time.monotonic() < deadline, "Plugin survived runner cleanup"
            time.sleep(0.02)
    except psutil.NoSuchProcess:
        pass
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_stderr_is_not_exposed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_kubectl(
        tmp_path, monkeypatch, "import sys; sys.stderr.write('secret'); sys.exit(1)"
    )
    with pytest.raises(subprocess.CalledProcessError) as error:
        command.run_kubectl("services,nodes", 2)
    assert error.value.stderr is None
    assert "secret" not in str(error.value)
