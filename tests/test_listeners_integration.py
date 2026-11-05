"""Rzeczywiste gniazda loopback; odczyt systemowy zależy od uprawnień OS."""

import os
import socket
import sys
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from portscanner.core.listeners import ListenerAccessDenied, collect_listeners
from portscanner.core.model import PortEntry
from portscanner.core.procs import enrich_processes


@pytest.mark.parametrize(
    "family,host", [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]
)
@pytest.mark.parametrize("system_wide", [False, True], ids=["own-process", "system"])
def test_real_local_sockets(
    monkeypatch: pytest.MonkeyPatch, system_wide: bool, family: int, host: str
) -> None:
    with ExitStack() as stack:
        tcp = stack.enter_context(socket.socket(family, socket.SOCK_STREAM))
        udp = stack.enter_context(socket.socket(family, socket.SOCK_DGRAM))
        udp_client = stack.enter_context(socket.socket(family, socket.SOCK_DGRAM))
        try:
            tcp.bind((host, 0))
        except OSError as exc:
            if family == socket.AF_INET6 and exc.errno in (49, 99, 10049):
                pytest.skip("IPv6 loopback niedostępny")
            raise
        tcp.listen(1)
        udp.bind((host, 0))
        udp_client.bind((host, 0))
        udp_client.connect(udp.getsockname())

        if not system_wide:
            # macOS pozwala odczytać własne gniazda bez root. Podstawiamy tylko
            # zakres odczytu; dane są rzeczywistymi rekordami psutil z PID.
            connections = [
                SimpleNamespace(
                    family=row.family,
                    type=row.type,
                    laddr=row.laddr,
                    raddr=row.raddr,
                    status=row.status,
                    pid=os.getpid(),
                )
                for row in psutil.Process().net_connections(kind="inet")
            ]
            monkeypatch.setattr(
                psutil, "net_connections", Mock(return_value=connections)
            )

        try:
            entries = collect_listeners()
        except ListenerAccessDenied:
            if system_wide:
                pytest.skip("Odczyt systemowy wymaga dodatkowych uprawnień OS")
            raise

        assert PortEntry("tcp", host, tcp.getsockname()[1], os.getpid()) in entries
        assert (
            PortEntry(
                "udp",
                host,
                udp.getsockname()[1],
                os.getpid(),
                udp_peer_status="unknown" if sys.platform == "win32" else "absent",
            )
            in entries
        )
        clients = [
            entry
            for entry in entries
            if entry.proto == "udp" and entry.port == udp_client.getsockname()[1]
        ]
        if sys.platform == "win32":
            assert clients and all(
                entry.udp_peer_status == "unknown" for entry in clients
            )
        else:
            assert not clients
        own_entries = [entry for entry in entries if entry.pid == os.getpid()]
        enriched = enrich_processes(own_entries)
        assert enriched
        for entry in enriched:
            assert entry.process is not None
            assert entry.process.status == "ok"
            assert entry.process.name
            assert entry.process.cmdline
