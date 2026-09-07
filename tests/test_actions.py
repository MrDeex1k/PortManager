"""Polityka kończenia procesów jest sprawdzana przed każdym sygnałem."""

import os
import socket
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import psutil
import pytest

from portscanner.core import actions

PID = 98765


@pytest.fixture
def process(monkeypatch: pytest.MonkeyPatch) -> Mock:
    target = Mock()
    target.name.return_value = "python3"
    target.exe.return_value = "/usr/bin/python3"
    target.cmdline.return_value = ["python3", "server.py"]
    target.create_time.return_value = 123.0
    target.is_running.return_value = True
    target.net_connections.return_value = [
        SimpleNamespace(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            status=psutil.CONN_LISTEN,
            laddr=SimpleNamespace(port=8080),
            raddr=(),
        )
    ]
    current = Mock()
    current.parents.return_value = []
    factory = Mock(side_effect=lambda pid=None: current if pid is None else target)
    monkeypatch.setattr(psutil, "Process", factory)
    monkeypatch.setattr(actions, "_same_owner", Mock(return_value=True))
    monkeypatch.setattr(actions, "_same_namespaces", Mock(return_value=True))
    return target


def test_prepare_never_sends_signal(process: Mock) -> None:
    target = actions.prepare_kill(PID)
    assert target.pid == PID and target.created_at == 123.0
    assert target.cmdline == ("python3", "server.py")
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


@pytest.mark.parametrize("pid", [0, 1, -1, True, os.getpid()])
def test_critical_pids_are_blocked_before_inspection(process: Mock, pid: int) -> None:
    with pytest.raises(actions.ProcessActionError):
        actions.prepare_kill(pid)
    process.name.assert_not_called()


def test_ancestor_is_protected(process: Mock) -> None:
    cast(Mock, psutil.Process()).parents.return_value = [SimpleNamespace(pid=PID)]
    with pytest.raises(actions.ProcessActionError, match="nadrzędny"):
        actions.prepare_kill(PID)


@pytest.mark.parametrize(
    "name", ["docker-proxy", "kubelet", "kube-apiserver", "custom-server"]
)
def test_protected_and_not_allowlisted_executables_are_blocked(
    process: Mock, name: str
) -> None:
    process.exe.return_value = "/usr/bin/" + name
    with pytest.raises(actions.ProcessActionError):
        actions.prepare_kill(PID)
    process.terminate.assert_not_called()


@pytest.mark.parametrize("check", ["_same_owner", "_same_namespaces"])
def test_foreign_owner_or_namespace_is_blocked(
    process: Mock, monkeypatch: pytest.MonkeyPatch, check: str
) -> None:
    monkeypatch.setattr(actions, check, Mock(return_value=False))
    with pytest.raises(actions.ProcessActionError):
        actions.prepare_kill(PID)


def test_process_without_port_is_blocked(process: Mock) -> None:
    process.net_connections.return_value = []
    with pytest.raises(actions.ProcessActionError, match="gniazda"):
        actions.prepare_kill(PID)


@pytest.mark.parametrize(
    "error", [psutil.AccessDenied(PID), psutil.NoSuchProcess(PID), OSError("failed")]
)
def test_read_error_never_allows_action(process: Mock, error: Exception) -> None:
    process.exe.side_effect = error
    with pytest.raises(actions.ProcessActionError):
        actions.prepare_kill(PID)
    process.terminate.assert_not_called()


def test_terminate_rechecks_identity_and_waits(process: Mock) -> None:
    target = actions.prepare_kill(PID)
    actions.terminate_target(target, timeout=0.2)
    assert process.create_time.call_count == 2
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=0.2)
    process.kill.assert_not_called()


@pytest.mark.parametrize(
    "field,value", [("create_time", 456.0), ("cmdline", ["python3", "different.py"])]
)
def test_reused_pid_or_changed_arguments_require_new_confirmation(
    process: Mock, field: str, value: object
) -> None:
    target = actions.prepare_kill(PID)
    getattr(process, field).return_value = value
    with pytest.raises(actions.ProcessActionError, match="zmieniły"):
        actions.terminate_target(target, force=True)
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


def test_lost_ownership_after_confirmation_is_blocked(
    process: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = actions.prepare_kill(PID)
    monkeypatch.setattr(actions, "_same_owner", Mock(return_value=False))
    with pytest.raises(actions.ProcessActionError):
        actions.terminate_target(target, force=True)
    process.terminate.assert_not_called()


def test_changed_secret_still_requires_new_confirmation(process: Mock) -> None:
    process.cmdline.return_value = ["python3", "server.py", "--token", "first-secret"]
    target = actions.prepare_kill(PID)
    assert target.cmdline[-1] == "first-secret"
    process.cmdline.return_value[-1] = "second-secret"
    with pytest.raises(actions.ProcessActionError, match="zmieniły"):
        actions.terminate_target(target)
    process.terminate.assert_not_called()


def test_unreadable_namespace_never_sends_signal(
    process: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        actions, "_same_namespaces", Mock(side_effect=PermissionError())
    )
    with pytest.raises(actions.ProcessActionError):
        actions.prepare_kill(PID)
    process.terminate.assert_not_called()


def test_timeout_without_force_does_not_kill(process: Mock) -> None:
    target = actions.prepare_kill(PID)
    process.wait.side_effect = psutil.TimeoutExpired(0.1)
    with pytest.raises(actions.ProcessActionError, match="Wysłano terminate"):
        actions.terminate_target(target, timeout=0.1)
    process.terminate.assert_called_once()
    process.kill.assert_not_called()


def test_force_rechecks_then_escalates_even_if_sockets_closed(process: Mock) -> None:
    target = actions.prepare_kill(PID)
    original_connections = process.net_connections.return_value
    process.net_connections.side_effect = [original_connections]
    process.wait.side_effect = [psutil.TimeoutExpired(0.1), 0]
    actions.terminate_target(target, force=True, timeout=0.1)
    assert process.create_time.call_count == 3
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2


def test_pid_change_before_escalation_never_kills(process: Mock) -> None:
    target = actions.prepare_kill(PID)
    process.create_time.side_effect = [123.0, 456.0]
    process.wait.side_effect = psutil.TimeoutExpired(0.1)
    with pytest.raises(actions.ProcessActionError, match="eskalacją"):
        actions.terminate_target(target, force=True, timeout=0.1)
    process.kill.assert_not_called()


@pytest.mark.parametrize(
    "args,allowed",
    [
        (("kubectl", "port-forward", "svc/web", "8080:80"), True),
        (("kubectl", "-n", "dev", "port-forward", "pod/web", "8080:80"), True),
        (("kubectl", "--context=local", "port-forward", "pod/web", "8080:80"), True),
        (("kubectl", "exec", "pod/web", "--", "port-forward"), False),
        (("kubectl", "get", "port-forward"), False),
    ],
)
def test_kubectl_allowlist_is_specific_to_port_forward(
    process: Mock, args: tuple[str, ...], allowed: bool
) -> None:
    process.name.return_value = "kubectl"
    process.exe.return_value = "/usr/bin/kubectl"
    process.cmdline.return_value = list(args)
    if allowed:
        assert actions.prepare_kill(PID).cmdline == args
    else:
        with pytest.raises(actions.ProcessActionError):
            actions.prepare_kill(PID)
