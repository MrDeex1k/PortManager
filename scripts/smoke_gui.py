"""Rzeczywisty smoke pywebview: gotowość Vue, mostek i zamknięcie okna.

Uruchamiaj jawnie w sesji graficznej, z zainstalowanym dodatkiem gui.
Sprawdza zainstalowany pakiet, również poza katalogiem repozytorium.
"""

import importlib
import json
import time
from unittest.mock import patch

from portscanner.gui import launch


def main() -> None:
    webview = importlib.import_module("webview")
    original_start = webview.start
    failures: list[str] = []

    def inspect() -> None:
        window = webview.windows[0]
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if window.events.loaded.wait(0.2):
                    state = window.evaluate_js(
                        "({rows: document.querySelectorAll('tbody tr').length, "
                        "desktop: document.body.innerText.includes('Okno desktopowe'), "
                        "icon: [...document.images].every(i => i.complete "
                        "&& i.naturalWidth > 0)})"
                    )
                    if state and state["rows"] == 8 and state["desktop"]:
                        assert state["icon"], "Nie załadowano ikony"
                        window.evaluate_js(
                            "document.querySelector('input').value = ':5432'; "
                            "document.querySelector('input').dispatchEvent("
                            "new Event('input', {bubbles: true}));"
                        )
                        time.sleep(0.2)
                        filtered = window.evaluate_js(
                            "({rows: document.querySelectorAll('tbody tr').length, "
                            "text: document.querySelector('tbody').innerText})"
                        )
                        assert filtered["rows"] == 1 and "5432" in filtered["text"]
                        print(
                            json.dumps(
                                {
                                    "gui": "ok",
                                    "bridge": "ok",
                                    "filter": "ok",
                                    "icon": "ok",
                                }
                            ),
                            flush=True,
                        )
                        break
                    time.sleep(0.2)
            else:
                raise AssertionError("Vue lub mostek nie zgłosiły gotowości w 20 s")
        except Exception as error:
            failures.append(str(error))
        finally:
            window.destroy()

    def start(**kwargs: object) -> None:
        original_start(inspect, **kwargs)

    with patch.object(webview, "start", start):
        launch()
    if failures:
        raise SystemExit("GUI smoke failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
