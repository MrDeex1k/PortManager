"""Rzeczywiste gniazda loopback; odczyt systemowy zależy od uprawnień OS."""

import os
import socket
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from portscanner.core.listeners import ListenerAccessDenied, collect_listeners
from portscanner.core.model import PortEntry
from portscanner.core.procs import enrich_processes


@pytest.mark.parametrize("system_wide", [False, True], ids=["own-process", "system"])
def test_real_local_sockets(monkeypatch: pytest.MonkeyPatch, system_wide: bool) -> None:
    with ExitStack() as stack:
        tcp = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        udp = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        udp_client = stack.enter_context(
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        )
        tcp.bind(("127.0.0.1", 0))
        tcp.listen(1)
        udp.bind(("127.0.0.1", 0))
        udp_client.bind(("127.0.0.1", 0))
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

        assert (
            PortEntry("tcp", "127.0.0.1", tcp.getsockname()[1], os.getpid()) in entries
        )
        assert (
            PortEntry("udp", "127.0.0.1", udp.getsockname()[1], os.getpid()) in entries
        )
        assert not any(
            entry.proto == "udp" and entry.port == udp_client.getsockname()[1]
            for entry in entries
        )
        own_entries = [entry for entry in entries if entry.pid == os.getpid()]
        enriched = enrich_processes(own_entries)
        assert enriched
        for entry in enriched:
            assert entry.process is not None
            assert entry.process.status == "ok"
            assert entry.process.name
            assert entry.process.cmdline
