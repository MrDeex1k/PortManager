"""Punkt wejścia pakietu. Właściwe CLI powstanie w Fazie 4."""

from typing import Annotated

import typer

app = typer.Typer(add_completion=False)


@app.command()
def status(
    cli: Annotated[
        bool, typer.Option("--cli", help="Tryb CLI (planowany w Fazie 4).")
    ] = False,
) -> None:
    """PortScanner: fundament repo gotowy, skanowanie w przygotowaniu."""
    mode = "CLI" if cli else "TUI"
    typer.echo(
        f"PortScanner: tryb {mode} nie jest jeszcze zaimplementowany. "
        "Ukończono Fazę 0; plan: docs/plan-mvp.md.",
        err=True,
    )
    raise typer.Exit(code=1)


def main() -> None:
    """Uruchom komendę zainstalowaną przez menedżer pakietów."""
    app()
