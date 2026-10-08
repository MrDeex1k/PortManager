"""Nieblokujący odczyt, ważność cache i zachowanie danych po awarii klastra."""

import threading
from unittest.mock import Mock

import pytest

from portscanner.core import kube_cache
from portscanner.core.kube_cache import KubeDiscovery
from portscanner.core.model import (
    Collection,
    KubernetesPort,
    LocalIP,
    PortEntry,
    SourceReport,
)
from tests.test_kube import forward

IPS = (LocalIP("en0", "192.0.2.1", "ipv4"),)
NODEPORT = PortEntry(
    "tcp",
    "192.0.2.1",
    31080,
    origin="kubernetes",
    kubernetes=(KubernetesPort("nodeport", "demo", "service/web", "80"),),
)
OK = Collection((NODEPORT,), SourceReport("kubernetes", "ok", "Konfiguracja NodePort."))


def finish(discovery: KubeDiscovery) -> None:
    worker = discovery._worker
    if worker is not None:
        worker.join(timeout=2)
        assert not worker.is_alive()


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock(return_value=OK)
    monkeypatch.setattr(kube_cache, "collect_nodeports", mock)
    return mock


def test_slow_cluster_does_not_block_local_rows_or_overlap(reader: Mock) -> None:
    entered, release = threading.Event(), threading.Event()

    def slow(*args: object, **kwargs: object) -> Collection[PortEntry]:
        entered.set()
        assert release.wait(2)
        return OK

    reader.side_effect = slow
    discovery = KubeDiscovery()
    row = forward("port-forward", "svc/web", "8080:80")
    try:
        result = discovery.collect((row,), IPS)
        assert entered.wait(1)
        assert result.items[0].kubernetes[0].kind == "port-forward"
        assert result.report.status == "partial"
        discovery.collect((), IPS)
        assert reader.call_count == 1
    finally:
        release.set()
        discovery.close()


def test_ttl_does_not_cache_local_sessions_and_reports_age(reader: Mock) -> None:
    clock = Mock(return_value=100.0)
    discovery = KubeDiscovery(clock=clock)
    try:
        discovery.collect((), IPS)
        finish(discovery)
        clock.return_value = 112.0
        row = forward("port-forward", "svc/web", "8080:80")
        result = discovery.collect((row,), IPS)
        assert len(result.items) == 2
        assert "12 s" in (result.report.message or "")
        assert discovery.collect((), IPS).items == (NODEPORT,)
        reader.assert_called_once_with(IPS, timeout=3.0)
        clock.return_value = 130.0
        discovery.collect((), IPS)
        finish(discovery)
        assert reader.call_count == 2
    finally:
        discovery.close()


def test_failed_refresh_retains_last_success_then_empty_success_clears_it(
    reader: Mock,
) -> None:
    clock = Mock(return_value=0.0)
    reader.side_effect = [
        OK,
        Collection((), SourceReport("kubernetes", "error", "Timeout klastra.")),
        Collection((), SourceReport("kubernetes", "ok")),
    ]
    discovery = KubeDiscovery(clock=clock)
    try:
        discovery.collect((), IPS)
        finish(discovery)
        clock.return_value = 30.0
        discovery.collect((), IPS)
        finish(discovery)
        result = discovery.collect((), IPS)
        assert result.items == (NODEPORT,)
        assert result.report.status == "partial"
        assert "Timeout" in (result.report.message or "")
        assert "30 s" in (result.report.message or "")
        clock.return_value = 60.0
        discovery.collect((), IPS)
        finish(discovery)
        result = discovery.collect((), IPS)
        assert not result.items and result.report.status == "ok"
    finally:
        discovery.close()


@pytest.mark.parametrize("reset", [False, True])
def test_ip_change_or_disable_discards_inflight_result(
    reader: Mock, reset: bool
) -> None:
    entered, release = threading.Event(), threading.Event()

    def slow(*args: object, **kwargs: object) -> Collection[PortEntry]:
        entered.set()
        assert release.wait(2)
        return OK

    reader.side_effect = slow
    discovery = KubeDiscovery()
    try:
        discovery.collect((), IPS)
        assert entered.wait(1)
        new_ips = IPS if reset else ()
        if reset:
            discovery.reset()
        assert not discovery.collect((), new_ips).items
        release.set()
        finish(discovery)
        reader.side_effect = None
        reader.return_value = Collection((), SourceReport("kubernetes", "ok"))
        assert not discovery.collect((), new_ips).items
        finish(discovery)
        assert not discovery.collect((), new_ips).items
        assert reader.call_count == 2
    finally:
        release.set()
        discovery.close()


def test_failure_is_throttled_and_never_exposes_exception(reader: Mock) -> None:
    reader.side_effect = RuntimeError("secret")
    discovery = KubeDiscovery(clock=lambda: 10.0)
    try:
        discovery.collect((), IPS)
        finish(discovery)
        result = discovery.collect((), IPS)
        assert result.report.status == "error"
        assert "secret" not in (result.report.message or "")
        discovery.collect((), IPS)
        assert reader.call_count == 1
    finally:
        discovery.close()
    with pytest.raises(RuntimeError, match="zamknięty"):
        discovery.collect((), IPS)


def test_manual_refresh_bypasses_ttl(reader: Mock) -> None:
    discovery = KubeDiscovery(clock=lambda: 1.0)
    try:
        discovery.collect((), IPS)
        finish(discovery)
        discovery.request_refresh()
        discovery.collect((), IPS)
        finish(discovery)
        assert reader.call_count == 2
    finally:
        discovery.close()


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_interval_is_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        KubeDiscovery(interval=value)
