# PortManager — PortScanner

Lokalny skaner portów. Pokazuje, **co słucha na Twoim komputerze** — port, proces, kontener Docker, tunel.

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

Cała logika mieszka w `portscanner/core/` — każdy interfejs to tylko inny widok tych samych danych.

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
uv sync
uv run portscanner          # TUI (domyślnie)
uv run portscanner --cli    # CLI
```

Wymagania: Python `>= 3.12` (dev: `3.13`), [`uv`](https://docs.astral.sh/uv/).

## Dokumentacja

| Plik | O czym |
|---|---|
| [`docs/mvp.md`](docs/mvp.md) | Pełna specyfikacja MVP: stack, decyzje, pułapki |
| [`docs/plan-mvp.md`](docs/plan-mvp.md) | Fazy realizacji z checkboxami |
| [`docs/conventional-commits.md`](docs/conventional-commits.md) | Format commitów + hooki |

## Status

MVP w budowie — plan w [`docs/plan-mvp.md`](docs/plan-mvp.md). Issue i PR mile widziane, ale najpierw rzuć okiem na docs.

Licencja: [GPLv3](LICENSE) © 2026 Jakub Batycki.
