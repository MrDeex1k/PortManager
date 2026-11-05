"""Zgoda dotyczy konkretnej, ponownie weryfikowanej tożsamości procesu."""

import json
import os

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Static

from portscanner.core.actions import KillTarget
from portscanner.core.model import Snapshot
from portscanner.core.redaction import redact_cmdline
from portscanner.presentation import report_text, safe_text, tunnel_text


class DiagnosticsScreen(ModalScreen[None]):
    """A keyboard-scrollable, complete diagnostic snapshot without height clipping."""

    BINDINGS = [("escape", "close", "Zamknij")]
    DEFAULT_CSS = """
    DiagnosticsScreen { align: center middle; background: $background 70%; }
    #diagnostics-scroll {
        width: 90%; height: 90%; border: thick $accent;
        padding: 1 2; background: $surface;
    }
    #diagnostics-scroll Static { height: auto; margin-bottom: 1; }
    """

    def __init__(self, snapshot: Snapshot) -> None:
        super().__init__()
        self.snapshot = snapshot

    def compose(self) -> ComposeResult:
        """Keep all source codes, local addresses and standalone connectors visible."""
        with VerticalScroll(id="diagnostics-scroll"):
            yield Static("Diagnostyka migawki — Esc zamyka", markup=False)
            yield Static(
                Text("\n".join(report_text(report) for report in self.snapshot.reports))
            )
            yield Static(
                Text(
                    "IP lokalne:\n"
                    + (
                        "\n".join(
                            safe_text(f"{ip.interface}: {ip.address}")
                            for ip in self.snapshot.local_ips
                        )
                        or "—"
                    )
                )
            )
            yield Static(
                Text(
                    "Connectory Cloudflare Tunnel (wszystkie):\n"
                    + ("\n".join(tunnel_text(t) for t in self.snapshot.tunnels) or "—")
                )
            )

    def on_mount(self) -> None:
        self.query_one("#diagnostics-scroll", VerticalScroll).focus()

    def action_close(self) -> None:
        self.dismiss(None)


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

    def __init__(self, target: KillTarget, *, escalation: bool = False) -> None:
        super().__init__()
        self.target = target
        self.escalation = escalation

    def compose(self) -> ComposeResult:
        """Render redacted identity and platform-specific termination consent."""
        with VerticalScroll():
            yield Static(
                "Wymusić zakończenie po timeout?"
                if self.escalation
                else "Zakończyć proces?",
                markup=False,
            )
            yield Static(
                Text(
                    safe_text(f"PID {self.target.pid}: {self.target.name}")
                    + "\nPlik: "
                    + safe_text(self.target.executable)
                    + "\nArgumenty: "
                    + json.dumps(redact_cmdline(self.target.cmdline), ensure_ascii=True)
                )
            )
            yield Static(
                "Proces zostanie ponownie zweryfikowany przed sygnałem. "
                "Operacja dotyczy całego procesu i wszystkich jego portów.",
                markup=False,
            )
            if os.name == "nt":
                yield Static("Windows: terminate oznacza twarde zakończenie procesu.")
            elif not self.escalation:
                yield Checkbox("Po timeout pozwól także na kill (--force)", id="force")
            if self.escalation:
                yield Static(
                    "Proces nadal działa po terminate. Zgoda dotyczy teraz kill."
                )
            with Horizontal():
                yield Button("Anuluj", id="cancel")
                yield Button("Zakończ proces", variant="error", id="confirm")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Return force consent only for confirmation; cancellation returns None."""
        event.stop()
        self.dismiss(
            (
                self.query_one("#force", Checkbox).value
                if not self.escalation and os.name != "nt"
                else self.escalation
            )
            if event.button.id == "confirm"
            else None
        )
