"""Wspólna polityka kończenia procesów dla CLI i TUI."""

import math
import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from typing import Literal

import psutil

from portscanner.core.k8s import executable_name
from portscanner.core.namespaces import same_namespaces as _same_namespaces

# Zamknięta allowlista; nowy typ procesu wymaga świadomej zmiany polityki.
_ALLOWED = {
    "node",
    "nodejs",
    "bun",
    "deno",
    "php",
    "ruby",
    "java",
    "dotnet",
    "uvicorn",
    "gunicorn",
    "flask",
    "rails",
}
_PROTECTED = {
    "docker-proxy",
    "dockerd",
    "containerd",
    "kubelet",
    "kube-apiserver",
    "kube-proxy",
    "kube-controller-manager",
    "kube-scheduler",
    "k3s",
    "kubelite",
    "microk8s",
    "etcd",
    "init",
    "systemd",
    "launchd",
    "svchost",
    "csrss",
    "lsass",
    "wininit",
    "services",
}


class ProcessActionError(RuntimeError):
    """Procesu nie można zakończyć zgodnie z polityką lub operacja nie powiodła się."""


@dataclass(frozen=True, slots=True)
class KillTarget:
    """Dane pokazywane do potwierdzenia; każdorazowo sprawdzane przed sygnałem."""

    pid: int
    created_at: float
    name: str
    executable: str
    cmdline: tuple[str, ...]


def _port_forward(args: tuple[str, ...]) -> bool:
    index = 1
    while index < len(args):
        arg = args[index]
        if arg in ("-n", "--namespace", "--context", "--kubeconfig"):
            index += 2
        elif arg.startswith(("--namespace=", "--context=", "--kubeconfig=")):
            index += 1
        else:
            return arg == "port-forward"
    return False


def _allowed(name: str, args: tuple[str, ...]) -> bool:
    return (
        name in _ALLOWED
        or re.fullmatch(r"python(?:3(?:\.\d+)?)?", name) is not None
        or (name == "kubectl" and _port_forward(args))
    )


def _same_owner(process: psutil.Process) -> bool:
    if os.name == "nt":
        return process.username().casefold() == psutil.Process().username().casefold()
    uids = process.uids()
    return uids.real == os.getuid() and uids.effective == os.getuid()


def _has_local_socket(process: psutil.Process) -> bool:
    return any(
        connection.family in (socket.AF_INET, socket.AF_INET6)
        and connection.laddr
        and connection.laddr.port > 0
        and (
            (
                connection.type == socket.SOCK_STREAM
                and connection.status == psutil.CONN_LISTEN
            )
            or (connection.type == socket.SOCK_DGRAM and not connection.raddr)
        )
        for connection in process.net_connections(kind="inet")
    )


def _inspect(
    pid: int, *, require_socket: bool = True
) -> tuple[psutil.Process, KillTarget]:
    if isinstance(pid, bool) or pid <= 1 or pid == os.getpid():
        raise ProcessActionError("PID 0/1 i własny proces skanera są chronione.")
    ancestors = {parent.pid for parent in psutil.Process().parents()}
    if pid in ancestors:
        raise ProcessActionError("Proces nadrzędny skanera jest chroniony.")
    process = psutil.Process(pid)
    if not _same_owner(process):
        raise ProcessActionError(
            "Można kończyć wyłącznie procesy bieżącego użytkownika."
        )
    if not _same_namespaces(pid):
        raise ProcessActionError("Proces ma inną przestrzeń sieciową lub montowania.")
    target = KillTarget(
        pid,
        process.create_time(),
        process.name(),
        process.exe(),
        tuple(process.cmdline()),
    )
    names = {executable_name(target.name), executable_name(target.executable)}
    if names & _PROTECTED:
        if "docker-proxy" in names:
            raise ProcessActionError(
                "docker-proxy jest chroniony; użyj docker stop <nazwa>."
            )
        raise ProcessActionError("Proces systemowy lub infrastruktury jest chroniony.")
    if not all(_allowed(name, target.cmdline) for name in names):
        raise ProcessActionError("Proces nie znajduje się na allowliście kończenia.")
    if require_socket and not _has_local_socket(process):
        raise ProcessActionError("Proces nie ma widocznego lokalnego gniazda TCP/UDP.")
    if not process.is_running():
        raise ProcessActionError("Proces zakończył się lub PID został użyty ponownie.")
    return process, target


def prepare_kill(pid: int) -> KillTarget:
    """Sprawdź warunki bez sygnału. UI musi uzyskać zgodę na pokazany KillTarget."""
    try:
        return _inspect(pid)[1]
    except psutil.NoSuchProcess as exc:
        raise ProcessActionError("Proces już nie istnieje.") from exc
    except (psutil.AccessDenied, PermissionError) as exc:
        raise ProcessActionError(
            "Brak uprawnień do pełnej weryfikacji procesu."
        ) from exc
    except (psutil.Error, OSError, RuntimeError) as exc:
        if isinstance(exc, ProcessActionError):
            raise
        raise ProcessActionError("Nie udało się zweryfikować procesu.") from exc


ActionStatus = Literal["terminated", "already_exited"]


class PendingTermination:
    """Single-use continuation, created only after a verified terminate timed out."""

    def __init__(self, target: KillTarget) -> None:
        self.target = target
        self._deadline = time.monotonic() + 120.0
        self._lock = threading.Lock()
        self._used = False

    def resume(self, *, timeout: float = 3.0) -> ActionStatus:
        """Caller must obtain a new explicit consent for kill before calling."""
        _validate_timeout(timeout)
        with self._lock:
            if self._used or time.monotonic() >= self._deadline:
                raise ProcessActionError(
                    "Potwierdzenie eskalacji wygasło lub zostało użyte."
                )
            self._used = True
        return _escalate(self.target, timeout)


class TerminationPending(ProcessActionError):
    def __init__(self, target: KillTarget) -> None:
        super().__init__(
            "Wysłano terminate, ale proces nie zakończył się przed timeoutem. "
            "Wymuszenie wymaga nowego potwierdzenia."
        )
        self.pending = PendingTermination(target)


def _validate_timeout(timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatni i skończony")


def _escalate(target: KillTarget, timeout: float) -> ActionStatus:
    try:
        # Only a continuation of an already verified and signalled operation
        # may omit the socket check. Ownership and identity are checked again.
        process, current = _inspect(target.pid, require_socket=False)
        if current != target:
            raise ProcessActionError("Tożsamość procesu zmieniła się przed eskalacją.")
        process.kill()
        process.wait(timeout=timeout)
        return "terminated"
    except psutil.NoSuchProcess as exc:
        # _inspect also reads ancestors. Their disappearance must not be
        # mistaken for completion of our target.
        try:
            candidate = psutil.Process(target.pid)
            gone = (
                candidate.create_time() != target.created_at
                or not candidate.is_running()
            )
        except psutil.NoSuchProcess:
            gone = True
        except (psutil.Error, OSError, RuntimeError):
            gone = False
        if gone:
            return "already_exited"
        raise ProcessActionError(
            "Nie udało się zweryfikować zakończenia procesu."
        ) from exc
    except psutil.TimeoutExpired as exc:
        raise ProcessActionError(
            "Proces nie zakończył się po kill przed timeoutem."
        ) from exc
    except (psutil.AccessDenied, PermissionError) as exc:
        raise ProcessActionError("Brak uprawnień do zakończenia procesu.") from exc
    except (psutil.Error, OSError, RuntimeError) as exc:
        if isinstance(exc, ProcessActionError):
            raise
        raise ProcessActionError("Nie udało się zakończyć procesu.") from exc


def terminate_target(
    target: KillTarget, *, force: bool = False, timeout: float = 3.0
) -> ActionStatus:
    """Verify consent, terminate, wait and optionally escalate.

    On Windows terminate is already a hard termination. A timeout without
    force returns a single-use continuation via TerminationPending; the UI
    must request fresh consent before resuming it, even if the port is gone.
    """
    _validate_timeout(timeout)
    try:
        process, current = _inspect(target.pid)
        if current != target:
            raise ProcessActionError(
                "Dane procesu zmieniły się; wymagane nowe potwierdzenie."
            )
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except psutil.TimeoutExpired as exc:
            if not force:
                raise TerminationPending(target) from exc
            return _escalate(target, timeout)
        except psutil.NoSuchProcess:
            return "already_exited"
        return "terminated"
    except psutil.NoSuchProcess as exc:
        raise ProcessActionError(
            "Proces zakończył się przed wysłaniem sygnału."
        ) from exc
    except (psutil.AccessDenied, PermissionError) as exc:
        raise ProcessActionError("Brak uprawnień do zakończenia procesu.") from exc
    except (psutil.Error, OSError, RuntimeError) as exc:
        if isinstance(exc, ProcessActionError):
            raise
        raise ProcessActionError("Nie udało się zakończyć procesu.") from exc
