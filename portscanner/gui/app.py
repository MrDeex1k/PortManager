"""Okno desktopowe ze spakowanymi zasobami lub lokalnym serwerem Vite."""

import importlib
import os
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit


class GuiLaunchError(RuntimeError):
    """Błąd startu, który CLI może pokazać bez tracebacka."""


class DesktopAPI:
    """Minimalny mostek Fazy 7.1. Nie odczytuje portów ani procesów."""

    def get_app_info(self) -> dict[str, str]:
        return {
            "name": "PortManager",
            "version": version("portscanner"),
            "mode": "desktop",
            "stage": "preview",
        }


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
        webview.create_window(
            "PortManager",
            url,
            js_api=DesktopAPI(),
            width=1320,
            height=860,
            min_size=(900, 620),
            background_color="#101113",
            text_select=True,
        )
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
