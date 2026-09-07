"""Kontrakt odczytu, filtrowania i grupowania gniazd systemowych."""

import socket
from typing import NamedTuple
from unittest.mock import Mock

import psutil
import pytest

from portscanner.core.listeners import (
    ListenerAccessDenied,
    ListenerScanError,
    collect_listeners,
)
from portscanner.core.model import PortEntry


class Address(NamedTuple):
    ip: str
    port: int


class Connection(NamedTuple):
    family: int = socket.AF_INET
    type: int = socket.SOCK_STREAM
    laddr: Address | tuple[()] = Address("127.0.0.1", 8080)
    raddr: Address | tuple[()] = ()
    status: str = psutil.CONN_LISTEN
    pid: int | None = 42


def source(monkeypatch: pytest.MonkeyPatch, *rows: Connection) -> Mock:
    mock = Mock(return_value=list(rows))
    monkeypatch.setattr(psutil, "net_connections", mock)
    return mock


def test_requests_only_internet_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = source(monkeypatch)
    assert collect_listeners() == []
    mock.assert_called_once_with(kind="inet")


@pytest.mark.parametrize(
    "status",
    [
        psutil.CONN_ESTABLISHED,
        psutil.CONN_TIME_WAIT,
        psutil.CONN_CLOSE_WAIT,
        psutil.CONN_SYN_SENT,
        psutil.CONN_NONE,
    ],
)
@pytest.mark.parametrize("port", [80, 60000])
def test_excludes_tcp_non_listeners(
    monkeypatch: pytest.MonkeyPatch, status: str, port: int
) -> None:
    source(monkeypatch, Connection(laddr=Address("127.0.0.1", port), status=status))
    assert collect_listeners() == []


@pytest.mark.parametrize("port", [1, 49152, 65535])
def test_keeps_tcp_listeners_regardless_of_port_number(
    monkeypatch: pytest.MonkeyPatch, port: int
) -> None:
    source(monkeypatch, Connection(laddr=Address("127.0.0.1", port), pid=None))
    assert collect_listeners() == [PortEntry("tcp", "127.0.0.1", port)]


def test_udp_uses_peer_not_tcp_state(monkeypatch: pytest.MonkeyPatch) -> None:
    bound = Connection(
        type=socket.SOCK_DGRAM,
        laddr=Address("127.0.0.1", 60000),
        status=psutil.CONN_NONE,
    )
    source(monkeypatch, bound, bound._replace(raddr=Address("127.0.0.1", 53)))
    assert collect_listeners() == [PortEntry("udp", "127.0.0.1", 60000, 42)]


@pytest.mark.parametrize(
    "row",
    [
        Connection(laddr=()),
        Connection(laddr=Address("0.0.0.0", 0)),
        Connection(family=socket.AF_UNSPEC),
        Connection(type=socket.SOCK_RAW),
        Connection(type=socket.SOCK_DGRAM, laddr=()),
    ],
)
def test_ignores_non_bound_or_unsupported_sockets(
    monkeypatch: pytest.MonkeyPatch, row: Connection
) -> None:
    source(monkeypatch, row)
    assert collect_listeners() == []


@pytest.mark.parametrize(
    "socket_type,proto", [(socket.SOCK_STREAM, "tcp"), (socket.SOCK_DGRAM, "udp")]
)
def test_groups_only_matching_wildcard_pair(
    monkeypatch: pytest.MonkeyPatch, socket_type: int, proto: str
) -> None:
    ipv4 = Connection(type=socket_type, laddr=Address("0.0.0.0", 8080))
    ipv6 = ipv4._replace(family=socket.AF_INET6, laddr=Address("::", 8080))
    source(monkeypatch, ipv6, ipv4, ipv4)
    grouped = collect_listeners()
    assert len(grouped) == 1
    assert (grouped[0].proto, grouped[0].bind, grouped[0].port, grouped[0].pid) == (
        proto,
        "*",
        8080,
        42,
    )
    assert {entry.bind for entry in collect_listeners(group_dual_stack=False)} == {
        "0.0.0.0",
        "::",
    }


@pytest.mark.parametrize("pids", [(42, 43), (None, None), (42, None), (None, 42)])
def test_does_not_merge_distinct_or_unknown_owners(
    monkeypatch: pytest.MonkeyPatch, pids: tuple[int | None, int | None]
) -> None:
    source(
        monkeypatch,
        Connection(laddr=Address("0.0.0.0", 8080), pid=pids[0]),
        Connection(family=socket.AF_INET6, laddr=Address("::", 8080), pid=pids[1]),
    )
    assert len(collect_listeners()) == 2
    assert all(entry.bind != "*" for entry in collect_listeners())


def test_keeps_protocols_ports_and_specific_addresses_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        Connection(laddr=Address("0.0.0.0", 8080)),
        Connection(family=socket.AF_INET6, laddr=Address("::", 8081)),
        Connection(
            type=socket.SOCK_DGRAM,
            family=socket.AF_INET6,
            laddr=Address("::", 8080),
            status=psutil.CONN_NONE,
        ),
        Connection(laddr=Address("127.0.0.1", 8080)),
        Connection(family=socket.AF_INET6, laddr=Address("::1", 8080)),
        Connection(laddr=Address("192.168.1.2", 8080)),
    ]
    mock = source(monkeypatch, *rows)
    expected = collect_listeners()
    assert len(expected) == len(rows)
    assert all(entry.bind != "*" for entry in expected)
    mock.return_value = list(reversed(rows))
    assert collect_listeners() == expected


def test_canonicalizes_ipv6_and_preserves_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source(
        monkeypatch,
        Connection(family=socket.AF_INET6, laddr=Address("0:0:0:0:0:0:0:1", 80)),
        Connection(family=socket.AF_INET6, laddr=Address("fe80::1%en0", 80)),
    )
    assert {entry.bind for entry in collect_listeners()} == {"::1", "fe80::1%en0"}


def test_same_address_with_unknown_and_known_pid_sorts_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source(monkeypatch, Connection(), Connection(pid=None))
    assert [entry.pid for entry in collect_listeners()] == [None, 42]


@pytest.mark.parametrize("error", [psutil.AccessDenied(), PermissionError("denied")])
def test_access_denied_is_not_an_empty_scan(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    mock = source(monkeypatch)
    mock.side_effect = error
    with pytest.raises(ListenerAccessDenied) as raised:
        collect_listeners()
    assert raised.value.__cause__ is error


@pytest.mark.parametrize("error", [OSError("failed"), psutil.Error("failed")])
def test_system_errors_have_a_core_exception(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    mock = source(monkeypatch)
    mock.side_effect = error
    with pytest.raises(ListenerScanError) as raised:
        collect_listeners()
    assert not isinstance(raised.value, ListenerAccessDenied)
    assert raised.value.__cause__ is error
