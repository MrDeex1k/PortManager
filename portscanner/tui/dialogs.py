"""Zgoda dotyczy konkretnej, ponownie weryfikowanej tożsamości procesu."""

import json

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Static

from portscanner.core.actions import KillTarget
from portscanner.presentation import safe_text


class KillScreen(ModalScreen[bool | None]):
    """None = anulowanie; bool = zgoda z opcjonalnym force po timeout."""

    BINDINGS = [("escape", "cancel", "Anuluj")]
    DEFAULT_CSS = """
    KillScreen { align: center middle; background: $background 70%; }
    KillScreen > VerticalScroll {
        width: 76; max-width: 95%; height: auto; max-height: 90%;
        border: thick $warning; padding: 1 2; background: $surface;
    }
    KillScreen Static { height: auto; margin-bottom: 1; }
    KillScreen Checkbox { width: 100%; height: auto; }
    KillScreen Horizontal { height: auto; align-horizontal: right; }
    KillScreen Button { margin: 1 0 0 1; }
    """

    def __init__(self, target: KillTarget) -> None:
        super().__init__()
        self.target = target

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("Zakończyć proces?", markup=False)
            yield Static(
                Text(
                    safe_text(f"PID {self.target.pid}: {self.target.name}")
                    + "\nPlik: "
                    + safe_text(self.target.executable)
                    + "\nArgumenty: "
                    + json.dumps(self.target.cmdline, ensure_ascii=True)
                )
            )
            yield Static(
                "Proces zostanie ponownie zweryfikowany przed terminate. "
                "Operacja dotyczy całego procesu i wszystkich jego portów.",
                markup=False,
            )
            yield Checkbox("Po timeout pozwól także na kill (--force)", id="force")
            with Horizontal():
                yield Button("Anuluj", id="cancel")
                yield Button("Zakończ proces", variant="error", id="confirm")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(
            self.query_one("#force", Checkbox).value
            if event.button.id == "confirm"
            else None
        )
