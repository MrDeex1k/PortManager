"""Pełny smoke GUI 7.5 na macOS z kontrolowanym własnym procesem."""

import importlib
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from portscanner.core.actions import KillTarget, terminate_target
from portscanner.core.model import (
    DockerPort,
    LocalIP,
    PortEntry,
    ProcessInfo,
    ServiceTag,
    Snapshot,
    SourceReport,
    TunnelRoute,
)
from portscanner.gui import app as gui_app


def _wait_js(window: object, expression: str, *, timeout: float = 8.0) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = window.evaluate_js(expression)  # type: ignore[attr-defined]
        if value:
            return value
        time.sleep(0.08)
    raise AssertionError(f"Timeout oczekiwania na warunek JS: {expression}")


def _listener() -> subprocess.Popen[str]:
    script = (
        "import socket, sys\n"
        "with socket.socket() as server:\n"
        " server.bind(('127.0.0.1', 0))\n"
        " server.listen()\n"
        " print(server.getsockname()[1], flush=True)\n"
        " sys.stdin.read()\n"
    )
    return subprocess.Popen(
        [sys.executable, "-u", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def main() -> None:
    webview = importlib.import_module("webview")
    original_start = webview.start
    failures: list[str] = []
    child = _listener()
    assert child.stdout is not None
    port_text = child.stdout.readline().strip()
    if not port_text.isdigit():
        stderr = child.stderr.read() if child.stderr else ""
        raise SystemExit(f"Nie udało się uruchomić procesu testowego: {stderr}")
    target_port = int(port_text)

    mapping = DockerPort(
        "a" * 64,
        "phase-7-api",
        "127.0.0.1",
        3000,
        3000,
        "tcp",
        "portmanager",
        "api",
    )
    route = TunnelRoute(9000, "preview.local", "localhost", 3000, "/api")

    def collector() -> Snapshot:
        time.sleep(0.65)
        entries = [
            PortEntry(
                "tcp",
                "127.0.0.1",
                3000,
                docker=(mapping,),
                tunnels=(route,),
                tags=(ServiceTag("k8s", "port"),),
            )
        ]
        if child.poll() is None:
            entries.append(
                PortEntry(
                    "tcp",
                    "127.0.0.1",
                    target_port,
                    child.pid,
                    ProcessInfo(
                        child.pid,
                        "ok",
                        Path(sys.executable).name,
                        (sys.executable, "-u", "-c", "<listener>"),
                    ),
                )
            )
        return Snapshot(
            ports=tuple(entries),
            local_ips=(LocalIP("lo0", "127.0.0.1", "ipv4"),),
            docker=(mapping,),
            tunnels=(),
            reports=(
                SourceReport("listeners", "ok"),
                SourceReport("processes", "partial", "Kontrolowany raport testowy."),
                SourceReport("docker", "ok"),
                SourceReport("tunnels", "ok"),
            ),
        )

    def slow_terminate(target: KillTarget, *, force: bool, timeout: float) -> None:
        time.sleep(0.65)
        terminate_target(target, force=force, timeout=timeout)

    api = gui_app.DesktopAPI(collector=collector, terminate=slow_terminate)

    with tempfile.TemporaryDirectory(prefix="portmanager-gui-smoke-") as directory:
        export_path = Path(directory) / "visible.json"

        def inspect() -> None:
            window = webview.windows[0]
            try:
                assert window.events.loaded.wait(10), "WebKit nie załadował dokumentu"
                window.evaluate_js(
                    "window.__smokeTicks=0; window.__smokeTimer=setInterval("
                    "()=>window.__smokeTicks++, 25)"
                )
                time.sleep(0.25)
                assert window.evaluate_js("window.__smokeTicks") >= 4

                _wait_js(window, "document.querySelectorAll('tbody tr').length === 2")
                assert window.evaluate_js(
                    "document.body.innerText.includes('Migawka jest częściowa')"
                )

                window.evaluate_js(
                    "[...document.querySelectorAll('th button')].find("
                    "b=>b.innerText.includes('Port')).click()"
                )
                _wait_js(
                    window,
                    "document.querySelector('tbody tr')?.dataset.port === "
                    f"'{target_port}'",
                )

                window.evaluate_js(
                    f"const i=document.querySelector('[data-testid=search]');"
                    f"i.value='pid:{child.pid}';"
                    "i.dispatchEvent(new Event('input',{bubbles:true}))"
                )
                _wait_js(window, "document.querySelectorAll('tbody tr').length === 1")
                window.evaluate_js("document.querySelector('tbody tr').click()")
                _wait_js(
                    window,
                    "Boolean(document.querySelector('[data-testid=kill-open]'))",
                )

                # Zaznaczenie musi przetrwać co najmniej jeden pełny cykl odświeżenia.
                time.sleep(2.8)
                assert window.evaluate_js(
                    "Boolean(document.querySelector('[data-testid=kill-open]'))"
                )

                with patch.object(
                    window,
                    "create_file_dialog",
                    return_value=(str(export_path),),
                ):
                    window.evaluate_js(
                        "document.querySelector('[data-testid=export]').click()"
                    )
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and not export_path.is_file():
                        time.sleep(0.08)
                    assert export_path.is_file(), "Eksport GUI nie utworzył pliku"
                exported = json.loads(export_path.read_text(encoding="utf-8"))
                expected = next(
                    entry for entry in collector().ports if entry.pid == child.pid
                )
                assert exported == [json.loads(json.dumps(asdict(expected)))]

                window.evaluate_js(
                    "document.querySelector('[data-testid=kill-open]').click()"
                )
                _wait_js(window, "document.querySelector('dialog[open]') !== null")
                assert window.evaluate_js(
                    "document.querySelector('[data-testid=force]').checked === false"
                )
                window.evaluate_js(
                    "document.querySelector('[data-testid=kill-cancel]').click()"
                )
                _wait_js(window, "document.querySelector('dialog[open]') === null")
                assert child.poll() is None, "Anulowanie zakończyło proces"

                window.evaluate_js(
                    "document.querySelector('[data-testid=kill-open]').click()"
                )
                _wait_js(window, "document.querySelector('dialog[open]') !== null")
                window.evaluate_js(
                    "document.querySelector('[data-testid=kill-confirm]').click()"
                )
                ticks_before = window.evaluate_js("window.__smokeTicks")
                time.sleep(0.3)
                assert window.evaluate_js("window.__smokeTicks") > ticks_before + 4
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and child.poll() is None:
                    time.sleep(0.08)
                assert child.poll() is not None, (
                    "Proces nie został zakończony przez GUI"
                )
                _wait_js(
                    window,
                    "!document.querySelector('[aria-label=\"Szczegóły portu\"]')",
                    timeout=8,
                )
                window.evaluate_js("clearInterval(window.__smokeTimer)")
                print(
                    json.dumps(
                        {
                            "gui": "ok",
                            "responsive": "ok",
                            "partial_report": "ok",
                            "filter_sort_refresh": "ok",
                            "selection": "ok",
                            "export": "ok",
                            "kill_cancel_confirm": "ok",
                            "close": "ok",
                        }
                    ),
                    flush=True,
                )
            except Exception as error:
                failures.append(f"{type(error).__name__}: {error}")
            finally:
                window.destroy()

        def start(**kwargs: object) -> None:
            original_start(inspect, **kwargs)

        try:
            with (
                patch.object(webview, "start", start),
                patch.object(gui_app, "DesktopAPI", return_value=api),
            ):
                gui_app.launch()
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=3)
    if failures:
        raise SystemExit("GUI smoke failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
