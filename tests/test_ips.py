"""Adresy lokalne nie potrzebują sieci; exit IP ma niezależną obsługę błędów."""

import socket
from email.message import Message
from http.client import IncompleteRead
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError, URLError

import psutil
import pytest

from portscanner.core import ips
from portscanner.core.model import LocalIP


def test_local_addresses_keep_interfaces_and_ipv6_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v4 = SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")
    v6 = SimpleNamespace(family=socket.AF_INET6, address="0:0:0:0:0:0:0:1")
    scoped = SimpleNamespace(family=socket.AF_INET6, address="fe80::1%en0")
    link = SimpleNamespace(family=psutil.AF_LINK, address="00:11:22:33:44:55")
    monkeypatch.setattr(
        psutil,
        "net_if_addrs",
        Mock(return_value={"vpn": [v4], "lo": [v6, v4, v4], "en0": [link, scoped]}),
    )
    network = Mock(side_effect=AssertionError("Nie wolno wysyłać żądania"))
    monkeypatch.setattr(ips, "urlopen", network)
    assert ips.collect_local_ips() == [
        LocalIP("en0", "fe80::1%en0", "ipv6"),
        LocalIP("lo", "127.0.0.1", "ipv4"),
        LocalIP("lo", "::1", "ipv6"),
        LocalIP("vpn", "127.0.0.1", "ipv4"),
    ]
    network.assert_not_called()


def test_no_interfaces_is_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "net_if_addrs", Mock(return_value={}))
    assert ips.collect_local_ips() == []


@pytest.mark.parametrize("error", [OSError("failed"), psutil.AccessDenied()])
def test_local_read_errors_are_explicit(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(psutil, "net_if_addrs", Mock(side_effect=error))
    with pytest.raises(ips.LocalIPError) as raised:
        ips.collect_local_ips()
    assert raised.value.__cause__ is error


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    response = MagicMock()
    response.status = 200
    response.read.return_value = b"8.8.8.8\n"
    response.__enter__.return_value = response
    opener = MagicMock(return_value=response)
    monkeypatch.setattr(ips, "urlopen", opener)
    return opener


@pytest.mark.parametrize(
    "payload,address,family",
    [
        (b"8.8.8.8\n", "8.8.8.8", "ipv4"),
        (b"2606:4700:4700:0:0:0:0:1111", "2606:4700:4700::1111", "ipv6"),
    ],
)
def test_exit_ip_validates_and_labels_response(
    http: MagicMock, payload: bytes, address: str, family: str
) -> None:
    http.return_value.read.return_value = payload
    result = ips.fetch_exit_ip(timeout=1.25)
    assert result.address == address
    assert result.family == family
    assert result.label == "exit IP (widziane z internetu)"
    assert result.source == "https://api64.ipify.org"
    assert http.call_args.args[0].full_url == result.source
    assert http.call_args.kwargs == {"timeout": 1.25}
    http.return_value.read.assert_called_once_with(65)
    http.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"<html>error</html>",
        b"8.8.8.8\n1.1.1.1",
        b"\xff",
        b"x" * 65,
        b"127.0.0.1",
        b"192.168.1.1",
        b"::1",
        b"ff02::1",
        b"2606:4700:4700::1111%en0",
    ],
)
def test_exit_ip_rejects_invalid_or_non_public_responses(
    http: MagicMock, payload: bytes
) -> None:
    http.return_value.read.return_value = payload
    with pytest.raises(ips.ExitIPError):
        ips.fetch_exit_ip()
    http.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timeout"),
        URLError("DNS unavailable"),
        HTTPError(ips.EXIT_IP_URL, 503, "unavailable", Message(), None),
        OSError("offline"),
    ],
)
def test_exit_network_errors_do_not_escape(http: MagicMock, error: Exception) -> None:
    http.side_effect = error
    with pytest.raises(ips.ExitIPError) as raised:
        ips.fetch_exit_ip()
    assert raised.value.__cause__ is error
    assert http.call_count == 1


@pytest.mark.parametrize(
    "error", [TimeoutError("read timeout"), IncompleteRead(b"8.8")]
)
def test_read_failure_closes_response(http: MagicMock, error: Exception) -> None:
    http.return_value.read.side_effect = error
    with pytest.raises(ips.ExitIPError):
        ips.fetch_exit_ip()
    http.return_value.__exit__.assert_called_once()


def test_unexpected_http_status(http: MagicMock) -> None:
    http.return_value.status = 204
    with pytest.raises(ips.ExitIPError):
        ips.fetch_exit_ip()
    http.return_value.read.assert_not_called()
    http.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_never_opens_connection(
    http: MagicMock, timeout: float
) -> None:
    with pytest.raises(ValueError):
        ips.fetch_exit_ip(timeout=timeout)
    http.assert_not_called()


def test_real_local_interfaces() -> None:
    assert any(entry.address == "127.0.0.1" for entry in ips.collect_local_ips())
