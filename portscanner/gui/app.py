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
from typing import Any
from urllib.parse import urlsplit

from portscanner.core.actions import (
    KillTarget,
    ProcessActionError,
    prepare_kill,
    terminate_target,
)
from portscanner.core.filtering import filter_entries
from portscanner.core.model import PortEntry, Snapshot
from portscanner.core.redaction import redact_cmdline
from portscanner.core.snapshot import collect_snapshot


class GuiLaunchError(RuntimeError):
    """Błąd startu, który CLI może pokazać bez tracebacka."""


class DesktopAPI:
    """Cienki mostek do core; pywebview wywołuje metody API poza wątkiem UI."""

    def __init__(
        self,
        *,
        collector: Callable[[], Snapshot] = collect_snapshot,
        prepare: Callable[[int], KillTarget] = prepare_kill,
        terminate: Callable[..., None] = terminate_target,
    ) -> None:
        self._collector = collector
        self._prepare = prepare
        self._terminate = terminate
        self._scan_lock = threading.Lock()
        self._action_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._snapshot: Snapshot | None = None
        self._generation = 0
        self._targets: dict[str, tuple[float, KillTarget]] = {}
        self._window: Any = None
        self._save_dialog_type: Any = None

    def _attach_window(self, window: Any, save_dialog_type: Any) -> None:
        self._window = window
        self._save_dialog_type = save_dialog_type

    def get_app_info(self) -> dict[str, str]:
        return {
            "name": "PortManager",
            "version": version("portscanner"),
            "mode": "desktop",
            "stage": "live",
        }

    def read_snapshot(self, request_id: int) -> dict[str, Any]:
        """Zbierz jedną migawkę; kolejny odczyt nie nakłada się na trwający."""
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            return _error("Nieprawidłowy identyfikator odświeżenia.", request_id=0)
        if not self._scan_lock.acquire(blocking=False):
            return {"ok": False, "busy": True, "request_id": request_id}
        try:
            try:
                snapshot = self._collector()
            except Exception:
                return _error(
                    "Nie udało się zebrać migawki systemu.", request_id=request_id
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
                "collected_at": datetime.now()
                .astimezone()
                .isoformat(timespec="seconds"),
                "ports": [_port_payload(entry) for entry in snapshot.ports],
                "local_ips": [asdict(item) for item in snapshot.local_ips],
                "reports": [asdict(report) for report in snapshot.reports],
            }
        finally:
            self._scan_lock.release()

    def filter_ports(self, generation: int, query: str | None) -> dict[str, Any]:
        """Filtruj kopię ostatniej migawki tym samym kodem co CLI i TUI."""
        with self._state_lock:
            snapshot = self._snapshot
            current = self._generation
        if snapshot is None or generation != current:
            return _error("Migawka zmieniła się; filtr zostanie ponowiony.")
        try:
            normalized = query if query and query.strip() else None
            entries = filter_entries(snapshot.ports, normalized)
        except ValueError as error:
            return _error(str(error), generation=current)
        return {
            "ok": True,
            "generation": current,
            "ids": [_port_id(entry) for entry in entries],
        }

    def export_ports(self, generation: int, ids: list[str]) -> dict[str, Any]:
        """Zapisz wybrany i uporządkowany widok przez natywny dialog plikowy."""
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            return _error("Nieprawidłowa lista wpisów do eksportu.")
        with self._state_lock:
            snapshot = self._snapshot
            current = self._generation
        if snapshot is None or generation != current:
            return _error("Migawka zmieniła się przed eksportem. Odśwież widok.")
        by_id = {_port_id(entry): entry for entry in snapshot.ports}
        if len(ids) != len(set(ids)) or any(item not in by_id for item in ids):
            return _error("Widok eksportu nie odpowiada bieżącej migawce.")
        if self._window is None:
            return _error("Natywny zapis jest dostępny w aplikacji desktopowej.")
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
            return _error("Nie udało się zapisać pliku JSON.")

    def prepare_process(self, pid: int) -> dict[str, Any]:
        """Utwórz krótkotrwałą zgodę przypisaną do zweryfikowanej tożsamości."""
        if isinstance(pid, bool) or not isinstance(pid, int):
            return _error("Nieprawidłowy PID.")
        try:
            target = self._prepare(pid)
        except ProcessActionError as error:
            return _error(str(error))
        token = uuid.uuid4().hex
        with self._state_lock:
            now = time.monotonic()
            self._targets = {
                key: value for key, value in self._targets.items() if value[0] > now
            }
            self._targets[token] = (now + 120.0, target)
        return {
            "ok": True,
            "token": token,
            "target": {
                "pid": target.pid,
                "name": target.name,
                "executable": target.executable,
                "cmdline": list(redact_cmdline(target.cmdline)),
            },
        }

    def terminate_process(self, token: str, force: bool = False) -> dict[str, Any]:
        """Zużyj zgodę raz; core ponownie sprawdzi proces przed każdym sygnałem."""
        if not isinstance(token, str) or not isinstance(force, bool):
            return _error("Nieprawidłowe potwierdzenie operacji.")
        if not self._action_lock.acquire(blocking=False):
            return _error("Inna operacja na procesie nadal trwa.", busy=True)
        try:
            with self._state_lock:
                prepared = self._targets.pop(token, None)
            if prepared is None or prepared[0] <= time.monotonic():
                return _error("Potwierdzenie wygasło. Zweryfikuj proces ponownie.")
            try:
                self._terminate(prepared[1], force=force, timeout=3.0)
            except ProcessActionError as error:
                return _error(str(error))
            return {"ok": True, "status": "terminated", "pid": prepared[1].pid}
        finally:
            self._action_lock.release()


def _error(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "message": message, **extra}


def _port_id(entry: PortEntry) -> str:
    return json.dumps(
        (entry.proto, entry.bind, entry.port, entry.pid, entry.origin),
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _port_payload(entry: PortEntry) -> dict[str, Any]:
    return {"id": _port_id(entry), **asdict(entry)}


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


def launch() -> None:
    """Start na głównym wątku; CLI/TUI nie potrzebują zależności GUI."""
    try:
        webview = importlib.import_module("webview")
    except ImportError as error:
        raise GuiLaunchError(
            "Brak zależności GUI. W repo wykonaj: uv sync --locked --extra gui. "
            "Przy instalacji pakietu wybierz portscanner[gui]."
        ) from error
    url = _window_url(os.environ.get("PORTSCANNER_GUI_DEV_URL"))
    try:
        api = DesktopAPI()
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
