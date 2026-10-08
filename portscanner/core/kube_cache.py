"""Odczyt klastra w tle dla interfejsów odświeżających lokalne porty."""

import math
import threading
import time
from collections.abc import Callable
from dataclasses import replace

from portscanner.core.kube import collect_nodeports, merge_kube
from portscanner.core.model import Collection, LocalIP, PortEntry, SourceReport


class KubeDiscovery:
    """Jedno żądanie naraz; cache przypisany do aktualnych lokalnych interfejsów."""

    def __init__(
        self,
        *,
        interval: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Interwał musi być dodatni i skończony")
        self._interval = interval
        self._clock = clock
        self._lock = threading.Lock()
        self._key: tuple[LocalIP, ...] | None = None
        self._revision = 0
        self._latest: Collection[PortEntry] | None = None
        self._success: Collection[PortEntry] | None = None
        self._completed_at = -math.inf
        self._success_at = 0.0
        self._worker: threading.Thread | None = None
        self._closed = False
        self._timeout = 3.0

    def reset(self) -> None:
        """Unieważnij dane i wynik trwającego odczytu po zmianie ustawienia."""
        with self._lock:
            self._invalidate(None)

    def request_refresh(self) -> None:
        """Ręczne odświeżenie omija TTL, zachowując dane do końca odczytu."""
        with self._lock:
            self._completed_at = -math.inf

    def _invalidate(self, key: tuple[LocalIP, ...] | None) -> None:
        self._revision += 1
        self._key = key
        self._latest = self._success = None
        self._completed_at = -math.inf

    def collect(
        self,
        entries: tuple[PortEntry, ...],
        local_ips: tuple[LocalIP, ...],
        *,
        timeout: float = 3.0,
    ) -> Collection[PortEntry]:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout musi być dodatni i skończony")
        with self._lock:
            if self._closed:
                raise RuntimeError("Odczyt Kubernetes jest zamknięty")
            if self._key != local_ips:
                self._invalidate(local_ips)
            now = self._clock()
            if self._worker is None and now - self._completed_at >= self._interval:
                self._timeout = timeout
                self._worker = threading.Thread(
                    target=self._read,
                    args=(local_ips, timeout, self._revision),
                    name="kubernetes-discovery",
                    daemon=True,
                )
                self._worker.start()
            result = self._latest
            if result is None:
                result = Collection(
                    (), SourceReport("kubernetes", "partial", "Odczyt klastra w toku.")
                )
            else:
                if result.report.status != "ok" and self._success is not None:
                    result = Collection(
                        self._success.items, replace(result.report, status="partial")
                    )
                age = max(0, now - self._success_at)
                message = result.report.message or ""
                if self._success is not None:
                    message += f" Dane klastra sprzed {age:.0f} s."
                if self._worker is not None:
                    message += " Odświeżanie klastra w tle."
                result = replace(result, report=replace(result.report, message=message))
        return merge_kube(entries, result)

    def _read(
        self, local_ips: tuple[LocalIP, ...], timeout: float, revision: int
    ) -> None:
        try:
            result = collect_nodeports(local_ips, timeout=timeout)
        except Exception:
            result = Collection(
                (), SourceReport("kubernetes", "error", "Odczyt klastra niedostępny.")
            )
        with self._lock:
            if revision == self._revision and not self._closed:
                self._latest = result
                self._completed_at = self._clock()
                if result.report.status == "ok":
                    self._success = result
                    self._success_at = self._completed_at
            self._worker = None

    def close(self) -> None:
        """Poczekaj na sprzątnięcie procesu przez ograniczony czasowo runner."""
        with self._lock:
            self._closed = True
            self._invalidate(None)
            worker = self._worker
        if worker is not None:
            worker.join(timeout=self._timeout + 2)
