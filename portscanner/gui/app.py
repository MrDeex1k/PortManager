"""Okno desktopowe ze spakowanymi zasobami lub lokalnym serwerem Vite."""

import importlib
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from portscanner.core.actions import (
    KillTarget,
    PendingTermination,
    ProcessActionError,
    TerminationPending,
    prepare_kill,
    terminate_target,
)
from portscanner.core.filtering import filter_entries
from portscanner.core.kube_cache import KubeDiscovery
from portscanner.core.model import PortEntry, Snapshot
from portscanner.core.redaction import redact_cmdline
from portscanner.core.snapshot import collect_snapshot
from portscanner.gui.contracts import (
    ActionSuccess,
    AppInfo,
    BridgeFailure,
    Cancelled,
    ErrorCode,
    ExportSaved,
    FilterSuccess,
    KubernetesSuccess,
    PrepareSuccess,
    SnapshotSuccess,
)
from portscanner.gui.core_payloads import (
    LocalIPPayload,
    PortEntryPayload,
    SourceReportPayload,
    TunnelInfoPayload,
)


class GuiLaunchError(RuntimeError):
    """Błąd startu, który CLI może pokazać bez tracebacka."""


class DesktopAPI:
    """Cienki mostek do core; pywebview wywołuje metody API poza wątkiem UI."""

    def __init__(
        self,
        *,
        collector: Callable[[], Snapshot] | None = None,
        kube: bool = False,
        prepare: Callable[[int], KillTarget] = prepare_kill,
        terminate: Callable[..., object] = terminate_target,
    ) -> None:
        """Initialize scan, action and consent state with injectable collectors."""
        self._collector = collector or self._collect
        self._kube = kube
        self._kube_discovery = KubeDiscovery()
        self._prepare = prepare
        self._terminate = terminate
        self._scan_lock = threading.Lock()
        self._action_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._snapshot: Snapshot | None = None
        self._generation = 0
        self._targets: dict[
            str, tuple[float, KillTarget, PendingTermination | None]
        ] = {}
        self._expiry_timer: threading.Timer | None = None
        self._closed = False
        self._window: Any = None
        self._save_dialog_type: Any = None

    def _attach_window(self, window: Any, save_dialog_type: Any) -> None:
        self._window = window
        self._save_dialog_type = save_dialog_type

    def _collect(self) -> Snapshot:
        return collect_snapshot(kube=self._kube, kube_discovery=self._kube_discovery)

    def _close(self) -> None:
        """Release retained process identities and stop consent timers and discovery."""
        with self._state_lock:
            self._closed = True
            self._targets.clear()
            if self._expiry_timer is not None:
                self._expiry_timer.cancel()
                self._expiry_timer = None
        self._kube_discovery.close()

    def _expire_targets(self) -> None:
        with self._state_lock:
            self._schedule_expiry()

    def _schedule_expiry(self) -> None:
        """Called under state lock; one timer releases raw argv at expiry."""
        if self._expiry_timer is not None:
            self._expiry_timer.cancel()
            self._expiry_timer = None
        now = time.monotonic()
        self._targets = {
            key: value for key, value in self._targets.items() if value[0] > now
        }
        if self._targets and not self._closed:
            delay = max(0.001, min(item[0] for item in self._targets.values()) - now)
            self._expiry_timer = threading.Timer(delay, self._expire_targets)
            self._expiry_timer.daemon = True
            self._expiry_timer.start()

    def _store_target(
        self,
        target: KillTarget,
        pending: PendingTermination | None = None,
    ) -> PrepareSuccess | BridgeFailure:
        """Retain an identity for 120 seconds; expose redacted consent details."""
        token = uuid.uuid4().hex
        with self._state_lock:
            if self._closed:
                return _error("Aplikacja jest zamknięta.", "consent_expired")
            self._targets[token] = (time.monotonic() + 120.0, target, pending)
            self._schedule_expiry()
        return {
            "ok": True,
            "token": token,
            "escalation": pending is not None,
            "target": {
                "pid": target.pid,
                "name": target.name,
                "executable": target.executable,
                "cmdline": list(redact_cmdline(target.cmdline)),
            },
        }

    def cancel_process(self, token: str) -> Cancelled | BridgeFailure:
        """Forget a consent token without a signal; repeated cancellation is safe."""
        if not isinstance(token, str):
            return _error("Nieprawidłowe potwierdzenie operacji.")
        with self._state_lock:
            self._targets.pop(token, None)
            self._schedule_expiry()
        return {"ok": True, "status": "cancelled"}

    def get_app_info(self) -> AppInfo:
        """Expose runtime metadata and the platform-specific termination mode."""
        return {
            "name": "PortManager",
            "version": version("portscanner"),
            "mode": "desktop",
            "stage": "live",
            "termination_mode": "hard" if os.name == "nt" else "graceful",
            "kube_enabled": self._kube,
        }

    def set_kubernetes(self, enabled: bool) -> KubernetesSuccess | BridgeFailure:
        """Jawne włączenie odczytu klastra także przy uruchomieniu z Findera."""
        if not isinstance(enabled, bool):
            return _error("Nieprawidłowe ustawienie Kubernetes.")
        if not self._scan_lock.acquire(blocking=False):
            return _error("Poczekaj na zakończenie odświeżania.", busy=True)
        try:
            if self._kube != enabled:
                self._kube = enabled
                self._kube_discovery.reset()
                with self._state_lock:
                    self._generation += 1
                    self._snapshot = None
            return {"ok": True, "kube_enabled": self._kube}
        finally:
            self._scan_lock.release()

    def read_snapshot(
        self, request_id: int, refresh_kube: bool = False
    ) -> SnapshotSuccess | BridgeFailure:
        """Zbierz jedną migawkę; kolejny odczyt nie nakłada się na trwający."""
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            return _error("Nieprawidłowy identyfikator odświeżenia.", request_id=0)
        if not isinstance(refresh_kube, bool):
            return _error(
                "Nieprawidłowe ustawienie odświeżenia.", request_id=request_id
            )
        if not self._scan_lock.acquire(blocking=False):
            return _error(
                "Odświeżanie jest w toku.", "busy", busy=True, request_id=request_id
            )
        try:
            if refresh_kube and self._kube:
                self._kube_discovery.request_refresh()
            try:
                snapshot = self._collector()
            except Exception:
                return _error(
                    "Nie udało się zebrać migawki systemu.",
                    "collection_failed",
                    request_id=request_id,
                )
            with self._state_lock:
                self._generation += 1
                generation = self._generation
                self._snapshot = snapshot
            return {
                "ok": True,
                "busy": False,
                "request_id": request_id,
                "generation": generation,
                "kube_enabled": self._kube,
                "collected_at": datetime.now()
                .astimezone()
                .isoformat(timespec="seconds"),
                "ports": [_port_payload(entry) for entry in snapshot.ports],
                "local_ips": [
                    cast(LocalIPPayload, asdict(item)) for item in snapshot.local_ips
                ],
                "reports": [
                    cast(SourceReportPayload, asdict(report))
                    for report in snapshot.reports
                ],
                "tunnels": [
                    cast(TunnelInfoPayload, asdict(tunnel))
                    for tunnel in snapshot.tunnels
                ],
            }
        finally:
            self._scan_lock.release()

    def filter_ports(
        self, generation: int, query: str | None
    ) -> FilterSuccess | BridgeFailure:
        """Filtruj kopię ostatniej migawki tym samym kodem co CLI i TUI."""
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or (query is not None and not isinstance(query, str))
        ):
            return _error("Nieprawidłowe argumenty filtra.")
        with self._state_lock:
            snapshot = self._snapshot
            current = self._generation
        if snapshot is None or generation != current:
            return _error(
                "Migawka zmieniła się; filtr zostanie ponowiony.", "stale_snapshot"
            )
        try:
            normalized = query if query and query.strip() else None
            entries = filter_entries(snapshot.ports, normalized)
        except ValueError as error:
            return _error(str(error), "invalid_filter", generation=current)
        return {
            "ok": True,
            "generation": current,
            "ids": [_port_id(entry) for entry in entries],
        }

    def export_ports(
        self, generation: int, ids: list[str]
    ) -> ExportSaved | Cancelled | BridgeFailure:
        """Zapisz wybrany i uporządkowany widok przez natywny dialog plikowy."""
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            return _error("Nieprawidłowa lista wpisów do eksportu.")
        with self._state_lock:
            snapshot = self._snapshot
            current = self._generation
        if snapshot is None or generation != current:
            return _error(
                "Migawka zmieniła się przed eksportem. Odśwież widok.", "stale_snapshot"
            )
        by_id = {_port_id(entry): entry for entry in snapshot.ports}
        if len(ids) != len(set(ids)) or any(item not in by_id for item in ids):
            return _error(
                "Widok eksportu nie odpowiada bieżącej migawce.", "invalid_selection"
            )
        if self._window is None:
            return _error(
                "Natywny zapis jest dostępny w aplikacji desktopowej.",
                "desktop_required",
            )
        filename = f"portmanager-{datetime.now():%Y%m%d-%H%M%S}.json"
        try:
            selection = self._window.create_file_dialog(
                self._save_dialog_type,
                save_filename=filename,
                file_types=("JSON (*.json)",),
            )
            if not selection:
                return {"ok": True, "status": "cancelled"}
            raw_path = (
                selection[0] if isinstance(selection, (tuple, list)) else selection
            )
            path = Path(raw_path)
            data = [asdict(by_id[item]) for item in ids]
            path.write_text(
                json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
            )
            return {"ok": True, "status": "saved", "path": str(path)}
        except (OSError, TypeError, ValueError):
            return _error("Nie udało się zapisać pliku JSON.", "export_failed")

    def prepare_process(self, pid: int) -> PrepareSuccess | BridgeFailure:
        """Utwórz krótkotrwałą zgodę przypisaną do zweryfikowanej tożsamości."""
        if isinstance(pid, bool) or not isinstance(pid, int):
            return _error("Nieprawidłowy PID.")
        try:
            target = self._prepare(pid)
        except ProcessActionError as error:
            return _error(str(error), "process_rejected")
        return self._store_target(target)

    def terminate_process(
        self, token: str, force: bool = False
    ) -> ActionSuccess | BridgeFailure:
        """Zużyj zgodę raz; core ponownie sprawdzi proces przed każdym sygnałem."""
        if not isinstance(token, str) or not isinstance(force, bool):
            return _error("Nieprawidłowe potwierdzenie operacji.")
        if not self._action_lock.acquire(blocking=False):
            return _error("Inna operacja na procesie nadal trwa.", busy=True)
        try:
            with self._state_lock:
                prepared = self._targets.pop(token, None)
                self._schedule_expiry()
            if prepared is None or prepared[0] <= time.monotonic():
                return _error(
                    "Potwierdzenie wygasło. Zweryfikuj proces ponownie.",
                    "consent_expired",
                )
            try:
                if prepared[2] is not None:
                    if not force:
                        return _error(
                            "Eskalacja wymaga jawnej zgody na kill.", "process_rejected"
                        )
                    status = prepared[2].resume(timeout=3.0)
                else:
                    status = self._terminate(prepared[1], force=force, timeout=3.0)
            except TerminationPending as error:
                continuation = self._store_target(prepared[1], error.pending)
                result = _error(str(error), "termination_pending")
                if continuation["ok"] is True:
                    result["continuation"] = continuation
                return result
            except ProcessActionError as error:
                return _error(str(error), "process_rejected")
            return {
                "ok": True,
                "status": "already_exited"
                if status == "already_exited"
                else "terminated",
                "pid": prepared[1].pid,
            }
        finally:
            self._action_lock.release()


def _error(
    message: str,
    code: ErrorCode = "invalid_request",
    *,
    busy: bool = False,
    request_id: int | None = None,
    generation: int | None = None,
) -> BridgeFailure:
    """Build a typed failure with optional request and snapshot correlation fields."""
    result: BridgeFailure = {
        "ok": False,
        "code": "busy" if busy else code,
        "message": message,
    }
    if busy:
        result["busy"] = True
    if request_id is not None:
        result["request_id"] = request_id
    if generation is not None:
        result["generation"] = generation
    return result


def _port_id(entry: PortEntry) -> str:
    return json.dumps(
        (entry.proto, entry.bind, entry.port, entry.pid, entry.origin),
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _port_payload(entry: PortEntry) -> PortEntryPayload:
    return cast(PortEntryPayload, {"id": _port_id(entry), **asdict(entry)})


def _window_url(dev_url: str | None) -> str:
    if dev_url is not None:
        # Mostek wolno udostępnić tylko świadomie uruchomionemu Vite na loopback.
        # Stały port chroni też przed cichym przeskokiem Vite na inną aplikację.
        if dev_url != "http://127.0.0.1:5173":
            raise GuiLaunchError(
                "PORTSCANNER_GUI_DEV_URL musi mieć wartość http://127.0.0.1:5173."
            )
        return dev_url + "/?desktop=1"
    entry = Path(__file__).parent / "assets" / "index.html"
    if not entry.is_file():
        raise GuiLaunchError(
            "Brak zasobów GUI. W repo wykonaj: "
            "cd frontend && bun install --frozen-lockfile && bun run build. "
            "Dla instalacji pipx użyj wheel z zasobami GUI."
        )
    return str(entry.resolve())


def launch(*, kube: bool = False) -> None:
    """Start na głównym wątku; CLI/TUI nie potrzebują zależności GUI."""
    try:
        webview = importlib.import_module("webview")
    except ImportError as error:
        raise GuiLaunchError(
            "Brak zależności GUI. W repo wykonaj: uv sync --locked --extra gui. "
            "Przy instalacji pakietu wybierz portscanner[gui]."
        ) from error
    url = _window_url(os.environ.get("PORTSCANNER_GUI_DEV_URL"))
    api = DesktopAPI(kube=kube)
    try:
        window = webview.create_window(
            "PortManager",
            url,
            js_api=api,
            width=1320,
            height=860,
            min_size=(900, 620),
            background_color="#101113",
            text_select=True,
        )
        api._attach_window(window, webview.SAVE_DIALOG)
        icon = Path(__file__).parent / "icons" / "portmanager.icns"
        webview.start(
            http_server=urlsplit(url).scheme != "http",
            debug=False,
            icon=str(icon) if icon.is_file() else None,
        )
    except Exception as error:
        raise GuiLaunchError(
            "Nie udało się uruchomić okna GUI. Sprawdź sesję graficzną "
            "i instalację pywebview dla swojego systemu."
        ) from error
    finally:
        api._close()
