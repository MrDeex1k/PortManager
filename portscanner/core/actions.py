"""Wspólna polityka kończenia procesów dla CLI i przyszłego TUI."""

import math
import os
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil

from portscanner.core.k8s import executable_name

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


def _same_namespaces(pid: int) -> bool:
    if sys.platform != "linux":
        return True
    return all(
        Path(f"/proc/{pid}/ns/{kind}").stat().st_ino
        == Path(f"/proc/self/ns/{kind}").stat().st_ino
        for kind in ("net", "mnt")
    )


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
    except (psutil.Error, OSError) as exc:
        raise ProcessActionError("Nie udało się zweryfikować procesu.") from exc


def terminate_target(
    target: KillTarget, *, force: bool = False, timeout: float = 3.0
) -> None:
    """Po zgodzie UI zweryfikuj dane ponownie, terminate, wait, opcjonalnie kill.

    Na Windows terminate także jest twardym zakończeniem. Force upoważnia tylko
    do eskalacji po timeout; nie omija polityki. Nie wznawiamy zakończonego procesu.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatni i skończony")
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
                raise ProcessActionError(
                    "Wysłano terminate, ale proces nie zakończył się przed timeoutem. "
                    "Eskalacja wymaga --force i ponownego potwierdzenia."
                ) from exc
            # Proces podczas zamykania mógł już zwolnić gniazda.
            process, current = _inspect(target.pid, require_socket=False)
            if current != target:
                raise ProcessActionError(
                    "Tożsamość procesu zmieniła się przed eskalacją."
                ) from exc
            process.kill()
            process.wait(timeout=timeout)
    except psutil.NoSuchProcess as exc:
        # Nie sygnalizujemy sukcesu dla PID, którego nie udało się zweryfikować.
        raise ProcessActionError("Proces zakończył się podczas operacji.") from exc
    except psutil.TimeoutExpired as exc:
        raise ProcessActionError(
            "Proces nie zakończył się po kill przed timeoutem."
        ) from exc
    except (psutil.AccessDenied, PermissionError) as exc:
        raise ProcessActionError("Brak uprawnień do zakończenia procesu.") from exc
    except (psutil.Error, OSError) as exc:
        raise ProcessActionError("Nie udało się zakończyć procesu.") from exc
