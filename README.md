# PortManager — PortScanner

Lokalny skaner portów. Pokazuje, **co słucha na Twoim komputerze** — port, proces, kontener Docker, tunel.

> **Status: Faza 0 ukończona.** Istnieją instalowalny pakiet, model `PortEntry`
> i pierwszy test. Skanowanie, CLI i TUI są dopiero planowane; poniższa tabela
> i opis interfejsów pokazują docelowe MVP.

```text
 PROTO  BIND       PORT   PID    PROC            DOCKER           TUNNEL
 tcp    *:8080     8080   4123   my-app          web → 80 (cont)
 tcp    127.0.0.1  5432   918    postgres
 tcp    *:3000     3000   4123   my-app                               app.example.com
```

> Scope: tylko to urządzenie (`localhost`). Bez skanowania zdalnych hostów.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Python >= 3.12](https://img.shields.io/badge/python-%3E%3D3.12-blue)

---

## Trzy twarze, jedno serce

Docelowo cała logika będzie w `portscanner/core/` — każdy interfejs będzie widokiem tych samych danych.

### TUI — do patrzenia 👀

Interaktywna tabela w terminalu. Domyślny tryb: wpisz `portscanner` i patrz.

Filtr (`/`), sortowanie (`s`), odświeżanie co 2 s, ubijanie procesu (`k` z potwierdzeniem), eksport do JSON (`j`).

### CLI — do skryptów ⚙️

Jednorazowy wynik, idealny do automatyzacji:

```bash
portscanner --cli --json | jq '.[] | select(.port == 8080)'
portscanner --cli --filter :8080
portscanner --cli --kill 4123
```

### GUI — do klikania 🖱️

Lekka aplikacja desktopowa (`pywebview` + Vue) na tym samym `core/`. Status: **po MVP**.

---

## Start

```bash
uv sync --locked
uv run portscanner --help   # działa już w Fazie 0
uv run portscanner          # komunikat o braku TUI, kod wyjścia 1
uv run portscanner --cli    # komunikat o braku CLI, kod wyjścia 1
```

Wymagania: Python `>= 3.12` (dev: `3.13`), [`uv`](https://docs.astral.sh/uv/).

Po zainstalowaniu Lefthook wykonaj `lefthook install` (szczegóły w dokumentacji
commitów). Kontrole lokalne:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyrefly check
uv run --locked pytest
uv build
```

Pakowanie używa Hatchling i jawnego `[build-system]`, wymaganego dla komendy
pakietu przez [uv](https://docs.astral.sh/uv/concepts/projects/config/#build-systems).
Dystrybucja MVP pozostaje przez `pipx install git+https://github.com/MrDeex1k/PortManager.git`.
Obecny etap zapewnia tylko szkielet; pełny interfejs będzie dostępny po dalszych fazach.

## Dokumentacja

| Plik | O czym |
|---|---|
| [`docs/mvp.md`](docs/mvp.md) | Pełna specyfikacja MVP: stack, decyzje, pułapki |
| [`docs/plan-mvp.md`](docs/plan-mvp.md) | Fazy realizacji z checkboxami |
| [`docs/conventional-commits.md`](docs/conventional-commits.md) | Format commitów + hooki |

## Status

Faza 0 ukończona; następna jest Faza 1 — zbieranie lokalnych portów.
Plan w [`docs/plan-mvp.md`](docs/plan-mvp.md). CI na self-hosted Actions
(Ubuntu x86 + RPi 5B ARM64) czeka na przygotowanie maszyn; do tego czasu
obowiązuje weryfikacja manualna. Testy tego etapu wykonano na macOS / Python 3.13.

Licencja: [GPLv3](LICENSE) © 2026 Jakub Batycki.
