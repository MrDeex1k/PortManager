"""Smoke instalacji: uruchamiany przez Python z venv pipx, bez pytest/dev deps."""

import asyncio
import importlib
import json
import platform
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import portscanner
from portscanner.core.model import PortEntry, Snapshot, SourceReport
from portscanner.tui import PortScannerApp


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def check_cli_result(result: subprocess.CompletedProcess[str]) -> None:
    payload = json.loads(result.stdout)
    require(
        isinstance(payload, dict) and isinstance(payload.get("ports"), list),
        "CLI nie zwrócił migawki JSON.",
    )
    reports = payload.get("reports", [])
    listeners = [item for item in reports if item.get("source") == "listeners"]
    require(len(listeners) == 1, "Brak jednoznacznego raportu listeners.")
    report = listeners[0]
    complete = report["status"] == "ok" or (
        report["status"] == "partial" and report.get("code") == "udp_peer_unknown"
    )
    expected = 0 if complete else 1
    require(
        result.returncode == expected,
        "Kod wyjścia CLI nie odpowiada raportowi listeners.",
    )
    if not complete:
        require(
            f"listeners: {report['status']}" in result.stderr,
            "Brak diagnostyki niepełnego odczytu listeners.",
        )


async def check_tui() -> None:
    # Kontrolowana migawka sprawdza UI nawet przy odmowie odczytu systemowego.
    snapshot = Snapshot(
        (PortEntry("tcp", "127.0.0.1", 8080),),
        (),
        (),
        (),
        (SourceReport("listeners", "ok"),),
    )
    with (
        TemporaryDirectory() as directory,
        patch("portscanner.tui.app.collect_snapshot", return_value=snapshot),
    ):
        app = PortScannerApp(export_directory=Path(directory))
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            require(app.table.row_count == 1, "TUI nie pokazał portu testowego.")
            await pilot.press("/", ":", "8", "0", "8", "0", "escape", "s", "j")
            await app.workers.wait_for_complete()
            files = list(Path(directory).glob("*.json"))
            require(len(files) == 1, "TUI nie utworzył jednego eksportu.")
            require(
                json.loads(files[0].read_text())[0]["port"] == 8080,
                "Eksport TUI nie zawiera portu testowego.",
            )
            await pilot.press("q")
            require(not app.is_running, "TUI nie zakończył działania.")


def main() -> None:
    package = Path(portscanner.__file__).resolve()
    require(
        package.is_relative_to(Path(sys.prefix).resolve()),
        f"Import spoza venv: {package}",
    )
    command = sys.argv[1]
    help_result = subprocess.run(
        [command, "--help"], capture_output=True, text=True, timeout=30, check=True
    )
    require("--cli" in help_result.stdout, "Brak --cli w pomocy.")
    result = subprocess.run(
        [command, "--cli", "--json-snapshot", "--no-docker", "--no-tunnels"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    check_cli_result(result)
    print("CLI: migawka JSON i kod wyjścia zgodny z raportem listeners.")
    if "--gui" in sys.argv[2:]:
        importlib.import_module("webview")
        from portscanner.gui.app import DesktopAPI, _window_url

        entry = Path(_window_url(None))
        require(entry.is_relative_to(Path(sys.prefix).resolve()), "GUI spoza venv.")
        api = DesktopAPI()
        try:
            info = api.get_app_info()
            require(
                "mode" in info and info["mode"] == "desktop", "Błąd metadanych GUI."
            )
        finally:
            api._close()
        print("GUI: dodatek, zasoby i metadane OK (bez otwierania okna).")
    asyncio.run(check_tui())
    print(
        "TUI: start, filtr, sort, JSON i quit OK; "
        f"portscanner {version('portscanner')}."
    )
    print(f"Python {platform.python_version()} — import z venv pipx, bez źródeł repo.")


if __name__ == "__main__":
    main()
