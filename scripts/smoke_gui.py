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

import psutil

from portscanner.core.actions import KillTarget, terminate_target
from portscanner.core.model import (
    DockerPort,
    KubernetesPort,
    LocalIP,
    PortEntry,
    ProcessInfo,
    ServiceTag,
    Snapshot,
    SourceReport,
    TunnelInfo,
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


def _listener(*, escalation: bool = False) -> subprocess.Popen[str]:
    """Start an owned listener that can close its port before escalation."""
    script = (
        "import socket, sys\n"
        "with socket.socket() as server:\n"
        " server.bind(('127.0.0.1', 0))\n"
        " server.listen()\n"
        " print(server.getsockname()[1], flush=True)\n"
        " sys.stdin.read()\n"
    )
    if escalation:
        script = script.replace(
            "import socket, sys", "import socket, sys, signal"
        ).replace(
            " print(server.getsockname()[1], flush=True)",
            " signal.signal(signal.SIGTERM, lambda *_: server.close())\n"
            " print(server.getsockname()[1], flush=True)",
        )
    return subprocess.Popen(
        [sys.executable, "-u", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def main() -> None:
    """Exercise the GUI with controlled data and an owned process; clean up."""
    webview = importlib.import_module("webview")
    original_start = webview.start
    failures: list[str] = []
    escalation = "--escalation" in sys.argv
    child = _listener(escalation=escalation)
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
        """Supply synthetic integrations and the current state of the owned listener."""
        time.sleep(0.65)
        entries = [
            PortEntry(
                "tcp",
                "127.0.0.1",
                3000,
                docker=(mapping,),
                tunnels=(route,),
                tags=(ServiceTag("k8s", "port"),),
                origin="kubernetes" if api._kube else "socket",
                kubernetes=(
                    KubernetesPort(
                        "nodeport", "smoke", "service/web", "80", node="worker"
                    ),
                )
                if api._kube
                else (),
            )
        ]
        has_port = child.poll() is None
        if has_port and escalation:
            try:
                has_port = any(
                    c.status == psutil.CONN_LISTEN
                    for c in psutil.Process(child.pid).net_connections()
                )
            except psutil.NoSuchProcess:
                has_port = False
        if has_port:
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
            tunnels=(
                TunnelInfo(
                    9000, config_status="remote", metrics_status="ok", connections=4
                ),
            ),
            reports=(
                SourceReport("listeners", "ok"),
                SourceReport("processes", "partial", "Kontrolowany raport testowy."),
                SourceReport("docker", "ok"),
                SourceReport("tunnels", "ok"),
            )
            + (
                (SourceReport("kubernetes", "ok", "Dane klastra sprzed 0 s."),)
                if api._kube
                else ()
            ),
        )

    def slow_terminate(target: KillTarget, *, force: bool, timeout: float) -> None:
        time.sleep(0.65)
        terminate_target(target, force=force, timeout=timeout)

    api = gui_app.DesktopAPI(collector=collector, terminate=slow_terminate)
    read_snapshot = api.read_snapshot
    forced_refreshes: list[int] = []

    def busy_once(request_id: int, refresh_kube: bool = False) -> dict:
        """Simulate one busy refresh response before restoring normal snapshot reads."""
        if refresh_kube:
            forced_refreshes.append(request_id)
            if len(forced_refreshes) == 1:
                return {"ok": False, "busy": True, "request_id": request_id}
        return dict(read_snapshot(request_id, refresh_kube))

    with tempfile.TemporaryDirectory(prefix="portmanager-gui-smoke-") as directory:
        export_path = Path(directory) / "visible.json"

        def inspect() -> None:
            """Run GUI checks, record failures and close the test window."""
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
                _wait_js(
                    window,
                    "document.querySelector('[aria-label=\"Connectory tuneli\"]')"
                    "?.innerText.includes('remote')",
                )
                assert window.evaluate_js(
                    "document.body.innerText.includes('Migawka jest częściowa')"
                )

                window.evaluate_js(
                    "[...document.querySelectorAll('nav button')].find("
                    "b=>b.innerText.includes('Kubernetes')).click()"
                )
                _wait_js(window, "document.querySelectorAll('tbody tr').length === 0")
                _wait_js(
                    window,
                    "!document.querySelector('[data-testid=kubernetes-toggle]').disabled",
                )
                window.evaluate_js(
                    "document.querySelector('[data-testid=kubernetes-toggle]').click()"
                )
                _wait_js(
                    window,
                    "document.querySelector('[data-testid=kubernetes-toggle]')"
                    ".getAttribute('aria-checked') === 'true'",
                )
                _wait_js(window, "document.querySelectorAll('tbody tr').length === 1")
                _wait_js(
                    window, "!document.querySelector('[data-testid=refresh]').disabled"
                )
                window.evaluate_js(
                    "document.querySelector('[data-testid=refresh]').click()"
                )
                deadline = time.monotonic() + 10
                while len(forced_refreshes) < 2:
                    assert time.monotonic() < deadline, "Manual refresh lost after busy"
                    time.sleep(0.05)
                assert window.evaluate_js(
                    "document.body.innerText.includes('Dane klastra sprzed 0 s.')"
                )
                window.evaluate_js("document.querySelector('tbody tr').click()")
                _wait_js(
                    window,
                    "document.querySelector('.inspector')?.innerText.includes('service/web')",
                )
                assert not window.evaluate_js(
                    "Boolean(document.querySelector('[data-testid=kill-open]'))"
                )
                assert window.evaluate_js(
                    "document.querySelector('.inspector').innerText"
                    ".includes('Konfiguracja NodePort')"
                )
                _wait_js(
                    window,
                    "!document.querySelector('[data-testid=kubernetes-toggle]').disabled",
                )
                window.evaluate_js(
                    "document.querySelector('[data-testid=kubernetes-toggle]').click()"
                )
                _wait_js(window, "document.querySelectorAll('tbody tr').length === 0")
                _wait_js(
                    window,
                    "!document.querySelector('[data-testid=kubernetes-toggle]').disabled",
                )
                window.evaluate_js(
                    "document.querySelector('[data-testid=kubernetes-toggle]').click()"
                )
                _wait_js(window, "document.querySelectorAll('tbody tr').length === 1")
                window.evaluate_js(
                    "[...document.querySelectorAll('nav button')].find("
                    "b=>b.innerText.includes('Wszystkie porty')).click()"
                )
                _wait_js(window, "document.querySelectorAll('tbody tr').length === 2")
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
                deadline = time.monotonic() + 2
                while api._targets and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert not api._targets, "Anulowana zgoda pozostaje w backendzie"

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
                if escalation:
                    _wait_js(
                        window,
                        "document.querySelector('dialog[open]')"
                        "?.innerText.includes('Wymusić zakończenie')",
                    )
                    assert child.poll() is None, (
                        "Eskalacja nie może poprzedzać drugiej zgody"
                    )
                    _wait_js(
                        window, "document.querySelectorAll('tbody tr').length === 0"
                    )
                    assert not psutil.Process(child.pid).net_connections(), (
                        "Port powinien być zamknięty"
                    )
                    window.evaluate_js(
                        "document.querySelector('[data-testid=kill-confirm]').click()"
                    )
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
                            "kubernetes_filter_inspector": "ok",
                            "kubernetes_toggle": "ok",
                            "manual_refresh_busy_retry": "ok",
                            "responsive": "ok",
                            "partial_report": "ok",
                            "filter_sort_refresh": "ok",
                            "selection": "ok",
                            "export": "ok",
                            "kill_cancel_confirm": "ok",
                            "remote_connector": "ok",
                            "cancel_releases_consent": "ok",
                            "timeout_escalation": "ok"
                            if escalation
                            else "not_requested",
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
                patch.object(api, "read_snapshot", busy_once),
            ):
                gui_app.launch()
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=3)
    if failures:
        raise SystemExit("GUI smoke failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
