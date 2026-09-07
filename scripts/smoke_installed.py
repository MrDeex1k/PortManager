"""Smoke instalacji: uruchamiany przez Python z venv pipx, bez pytest/dev deps."""

import asyncio
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
            assert app.table.row_count == 1
            await pilot.press("/", ":", "8", "0", "8", "0", "escape", "s", "j")
            await app.workers.wait_for_complete()
            files = list(Path(directory).glob("*.json"))
            assert len(files) == 1
            assert json.loads(files[0].read_text())[0]["port"] == 8080
            await pilot.press("q")
            assert not app.is_running


def main() -> None:
    package = Path(portscanner.__file__).resolve()
    assert package.is_relative_to(Path(sys.prefix).resolve()), package
    command = sys.argv[1]
    help_result = subprocess.run(
        [command, "--help"], capture_output=True, text=True, timeout=30, check=True
    )
    assert "--cli" in help_result.stdout
    result = subprocess.run(
        [command, "--cli", "--json", "--no-docker", "--no-tunnels"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert isinstance(json.loads(result.stdout), list)
    assert result.returncode in (0, 1), result.stderr
    if result.returncode == 1:
        assert "listeners: error" in result.stderr, result.stderr
        print("CLI: poprawny JSON i jawny brak uprawnień odczytu systemowego.")
    else:
        print("CLI: odczyt systemowy i JSON OK.")
    asyncio.run(check_tui())
    print(
        "TUI: start, filtr, sort, JSON i quit OK; "
        f"portscanner {version('portscanner')}."
    )
    print(f"Python {platform.python_version()} — import z venv pipx, bez źródeł repo.")


if __name__ == "__main__":
    main()
