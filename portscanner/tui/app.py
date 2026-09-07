"""Nieblokujący widok migawek; polityka procesów pozostaje w core."""

import asyncio
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Static

from portscanner.core import collect_snapshot
from portscanner.core.actions import ProcessActionError, prepare_kill, terminate_target
from portscanner.core.filtering import filter_entries
from portscanner.core.model import PortEntry, Snapshot
from portscanner.presentation import COLUMNS, entry_cells, safe_text
from portscanner.tui.dialogs import KillScreen


def row_key(entry: PortEntry) -> str:
    # PID i pochodzenie rozróżniają współdzielone porty oraz publikacje Dockera.
    return json.dumps((entry.proto, entry.bind, entry.port, entry.pid, entry.origin))


def export_json(entries: tuple[PortEntry, ...], directory: Path) -> Path:
    """Nowy plik, bez nadpisania/symlinków; na POSIX dostęp tylko właściciela."""
    data = json.dumps([asdict(entry) for entry in entries], ensure_ascii=True, indent=2)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"portscanner-{stamp}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data + "\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


class PortScannerApp(App[None]):
    TITLE = "PortScanner"
    SUB_TITLE = "Lokalne porty"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("/", "filter", "Filtr"),
        ("s", "sort", "Sortuj"),
        ("r", "refresh", "Odśwież"),
        ("k", "kill", "Zakończ proces"),
        ("j", "export", "JSON"),
        ("q", "quit", "Wyjdź"),
        Binding("escape", "table", "Tabela", show=False),
        Binding("ctrl+q", "quit", "Wyjdź", show=False, priority=True),
    ]
    CSS = """
    Screen { layout: vertical; }
    #filter { margin: 0 1; }
    #summary { height: auto; max-height: 5; overflow-y: auto;
        padding: 0 1; color: $text-muted; }
    #reports { height: auto; max-height: 5; overflow-y: auto; padding: 0 1;
        color: $warning; }
    #ports { height: 1fr; margin: 0 1; }
    #message { height: auto; max-height: 3; padding: 0 1; }
    """

    def __init__(self, *, export_directory: Path | None = None) -> None:
        super().__init__()
        self.export_directory = export_directory or Path.cwd()
        self.snapshot: Snapshot | None = None
        self.table = DataTable[Text](id="ports", cursor_type="row", zebra_stripes=True)
        self.filter_input = Input(
            placeholder="Filtr: :8080, pid:42 lub tekst", id="filter"
        )
        self.summary = Static("Oczekiwanie na pierwszy odczyt…", id="summary")
        self.reports = Static("", id="reports", markup=False)
        self.message = Static("", id="message", markup=False)
        self._rows: dict[str, PortEntry] = {}
        self._sort_process = False
        self._refreshing = False
        self._action_busy = False
        self._exporting = False
        self._last_update = "—"
        self._filter_error = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield self.filter_input
        yield self.summary
        yield self.reports
        yield self.table
        yield self.message
        yield Footer()

    def on_mount(self) -> None:
        for column in COLUMNS:
            self.table.add_column(column, key=column)
        self.table.focus()
        self.set_interval(2.0, self.action_refresh)
        self.action_refresh()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("filter", "sort", "refresh", "kill", "export", "quit", "table"):
            if isinstance(self.screen, ModalScreen):
                return False
            if action != "table" and isinstance(self.focused, Input):
                return False
            if self._action_busy and action in ("kill", "export"):
                return False
        return True

    def action_filter(self) -> None:
        self.filter_input.focus()

    def action_table(self) -> None:
        self.table.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.table.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._render_rows()

    def action_sort(self) -> None:
        self._sort_process = not self._sort_process
        self._render_rows(sort=True)

    def action_refresh(self) -> None:
        # Nie anulujemy odczytu wątku: następny tick/r czeka na jego zakończenie.
        if not self._refreshing:
            self._refreshing = True
            self.run_worker(self._refresh(), group="snapshot")

    async def _refresh(self) -> None:
        try:
            snapshot = await asyncio.to_thread(collect_snapshot)
            self.snapshot = snapshot
            self._last_update = datetime.now().strftime("%H:%M:%S")
            self._render_rows()
            lines = [
                safe_text(f"{report.source}: {report.status} — {report.message or ''}")
                for report in snapshot.reports
                if report.status not in ("ok", "disabled")
            ]
            self.reports.update(Text("\n".join(lines)))
        except Exception as error:
            # Stara migawka zostaje widoczna, ale nie udaje aktualnego odczytu.
            self.reports.update(
                Text(
                    "Błąd odświeżania; zachowano poprzednie dane: "
                    + safe_text(str(error))
                )
            )
        finally:
            self._refreshing = False

    def _selected_key(self) -> str | None:
        if self.table.row_count:
            return self.table.coordinate_to_cell_key(
                self.table.cursor_coordinate
            ).row_key.value
        return None

    @property
    def visible_entries(self) -> tuple[PortEntry, ...]:
        return tuple(
            self._rows[row.key.value]
            for row in self.table.ordered_rows
            if row.key.value is not None
        )

    def _render_rows(self, *, sort: bool = False) -> None:
        if not self.table.columns:
            return
        try:
            entries = filter_entries(
                self.snapshot.ports if self.snapshot else (),
                self.filter_input.value.strip() or None,
            )
            self._filter_error = False
            self.filter_input.border_subtitle = None
        except ValueError as error:
            entries = []
            self._filter_error = True
            self.filter_input.border_subtitle = Text(safe_text(str(error)))
        selected = self._selected_key()
        previous_index = self.table.cursor_row
        rows = {row_key(entry): entry for entry in entries}
        changed = rows != self._rows
        with self.batch_update():
            for key in self._rows.keys() - rows.keys():
                self.table.remove_row(key)
            for key, entry in rows.items():
                cells = entry_cells(entry)
                previous = self._rows.get(key)
                if previous is None:
                    self.table.add_row(*(Text(cell) for cell in cells), key=key)
                elif previous != entry:
                    for column, old, new in zip(
                        COLUMNS, entry_cells(previous), cells, strict=True
                    ):
                        if old != new:
                            self.table.update_cell(
                                key, column, Text(new), update_width=True
                            )
            self._rows = rows
            if changed or sort:
                columns = ["PORT", "PROTO", "BIND", "PID", "ŹRÓDŁO"]
                if self._sort_process:
                    columns.insert(0, "PROC")
                self.table.sort(
                    *columns,
                    key=lambda cells: tuple(
                        int(cell.plain)
                        if column in ("PORT", "PID") and cell.plain != "?"
                        else -1
                        if column == "PID"
                        else cell.plain.casefold()
                        for column, cell in zip(columns, cells, strict=True)
                    ),
                )
                if rows:
                    index = (
                        self.table.get_row_index(selected)
                        if selected in rows
                        else min(previous_index, len(rows) - 1)
                    )
                    self.table.move_cursor(row=index, scroll=False)
        ips = (
            "; ".join(
                safe_text(f"{ip.interface}: {ip.address}")
                for ip in self.snapshot.local_ips
            )
            if self.snapshot
            else "—"
        )
        mode = "proces" if self._sort_process else "port"
        empty = " | Brak pasujących wpisów." if not rows else ""
        self.summary.update(
            Text(
                f"Wpisy: {len(rows)} | Sort: {mode} | "
                f"Odczyt: {self._last_update}{empty}\n"
                f"IP lokalne: {ips or '—'}\n"
                "UDP: związane gniazdo • docker: publikacja • tunel: reguła config"
            )
        )

    def action_export(self) -> None:
        if self.snapshot is None or self._filter_error:
            self.message.update("Eksport wymaga odczytu i poprawnego filtra.")
            return
        if not self._exporting:
            self._exporting = True
            self.run_worker(self._export(self.visible_entries), group="export")

    async def _export(self, entries: tuple[PortEntry, ...]) -> None:
        try:
            path = await asyncio.to_thread(export_json, entries, self.export_directory)
            self.message.update(
                Text(f"Zapisano {len(entries)} wpisów: {safe_text(str(path))}")
            )
        except Exception as error:
            self.message.update(
                Text("Eksport nie powiódł się: " + safe_text(str(error)))
            )
        finally:
            self._exporting = False

    def action_kill(self) -> None:
        if self._action_busy:
            return
        entry = self._rows.get(self._selected_key() or "")
        if entry is not None and entry.origin == "docker":
            self.message.update(
                "Publikacja Docker: zarządzaj kontenerem przez docker stop <nazwa>."
            )
            return
        if entry is None or entry.pid is None:
            self.message.update("Wybierz gniazdo ze znanym PID.")
            return
        self._action_busy = True
        self.refresh_bindings()
        self.run_worker(self._kill(entry.pid), group="process")

    async def _kill(self, pid: int) -> None:
        try:
            self.message.update(f"Weryfikacja procesu PID {pid}…")
            target = await asyncio.to_thread(prepare_kill, pid)
            force = await self.push_screen_wait(KillScreen(target))
            if force is None:
                self.message.update("Anulowano kończenie procesu.")
                return
            self.message.update(f"Kończenie procesu PID {target.pid}…")
            await asyncio.to_thread(terminate_target, target, force=force)
            self.message.update(f"Zakończono proces PID {target.pid}.")
            self.action_refresh()
        except ProcessActionError as error:
            self.message.update(Text(safe_text(str(error))))
        except Exception as error:
            self.message.update(Text("Błąd operacji procesu: " + safe_text(str(error))))
        finally:
            self._action_busy = False
            self.refresh_bindings()

    async def action_quit(self) -> None:
        if not self._action_busy and not self._exporting:
            self.exit()
        else:
            self.message.update("Poczekaj na zakończenie bieżącej operacji.")
