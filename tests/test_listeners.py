"""Kontrakt odczytu, filtrowania i grupowania gniazd systemowych."""

import socket
import sys
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


def test_malformed_address_does_not_discard_other_listeners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source(
        monkeypatch,
        Connection(laddr=Address("not-an-ip", 8081)),
        Connection(),
        Connection(family=socket.AF_INET6, laddr=Address("fe80::1%en0", 8082)),
    )
    assert collect_listeners() == [
        PortEntry("tcp", "127.0.0.1", 8080, 42),
        PortEntry("tcp", "fe80::1%en0", 8082, 42),
    ]


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
    """UDP inclusion depends on the remote peer rather than TCP connection state."""
    bound = Connection(
        type=socket.SOCK_DGRAM,
        laddr=Address("127.0.0.1", 60000),
        status=psutil.CONN_NONE,
    )
    source(monkeypatch, bound, bound._replace(raddr=Address("127.0.0.1", 53)))
    assert collect_listeners() == [
        PortEntry(
            "udp",
            "127.0.0.1",
            60000,
            42,
            udp_peer_status="unknown" if sys.platform == "win32" else "absent",
        )
    ]


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


def test_windows_udp_unknown_owner_and_peer(monkeypatch):
    """Windows UDP metadata preserves unknown ownership and peer visibility."""
    from types import SimpleNamespace

    from portscanner.core import listeners

    monkeypatch.setattr(listeners, "sys", SimpleNamespace(platform="win32"))
    connections = [
        SimpleNamespace(
            family=family,
            type=socket.SOCK_DGRAM,
            status=psutil.CONN_NONE,
            laddr=SimpleNamespace(ip=ip, port=5353),
            raddr=(),
            pid=0,
        )
        for family, ip in [(socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")]
    ]
    monkeypatch.setattr(psutil, "net_connections", Mock(return_value=connections))
    rows = collect_listeners()
    assert len(rows) == 2
    assert all(row.pid is None and row.udp_peer_status == "unknown" for row in rows)


def test_accessible_process_fallback_keeps_rows_when_other_process_denied(monkeypatch):
    from types import SimpleNamespace

    from portscanner.core.listeners import collect_accessible_listeners

    denied, allowed = Mock(), Mock()
    denied.net_connections.side_effect = psutil.AccessDenied(1)
    allowed.pid = 42
    allowed.net_connections.return_value = [
        SimpleNamespace(
            family=socket.AF_INET6,
            type=socket.SOCK_STREAM,
            status=psutil.CONN_LISTEN,
            laddr=SimpleNamespace(ip="::1", port=8080),
            raddr=(),
        )
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda: iter([denied, allowed]))
    result = collect_accessible_listeners()
    assert result.report.status == "partial"
    assert result.items == (PortEntry("tcp", "::1", 8080, 42),)
