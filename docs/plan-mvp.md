# Plan MVP — fazy

Stan na 2026-09-06. Źródło decyzji: `docs/mvp.md`.

Kontrakt wejścia (obowiązuje od Fazy 4, GUI po MVP):
- `portscanner` → TUI (domyślne)
- `portscanner --cli [--json] [--filter ...]` → CLI
- `portscanner --gui` → GUI (po MVP); w środowisku graficznym ikonka
  (`.desktop` / skrót w Menu Start / `.app`) odpala ten sam GUI —
  zawsze na tym samym `core/`, nigdy osobna logika.

Zasady przez cały plan:
- `core/` nie importuje UI (§1). Zero wyjątków.
- Ruff blokuje brudny commit (job `pre-commit` w `lefthook.yml` od Fazy 0).
- Pyrefly ręcznie (`uv run pyrefly check`); wymóg "zero błędów" zamyka każdą fazę.
- Kill w pełnym zakresie z §6 (allowlista + potwierdzenie) — to część definicji "gotowe", nie dodatek.

---

## Faza 0 — fundament repo `[ ]`

- [ ] §9 w całości zaklepany 2026-09-06; na starcie Fazy 0 zweryfikować najnowsze stabilne wersje (`uv lock`) zamiast pinu z §2
- [ ] Zacommitować obecny stan (`LICENSE`, `lefthook.yml`, `scripts/`, `docs/`)
- [ ] `lefthook install` + ruleset `Require commit message pattern` na GitHubie
- [ ] `uv init` → `pyproject.toml` (`[project.scripts]` z entry `portscanner`), `.python-version=3.13`
- [ ] `uv add psutil pyyaml textual typer` + `uv add --dev ruff pyrefly pytest`, `uv sync`
- [ ] Ruff jako blokujący `pre-commit` w `lefthook.yml`
- [ ] Szkielet `portscanner/core/model.py` (`PortEntry`) + pierwszy test `pytest`
- [ ] Decyzja zapisana: dystrybucja MVP = `pipx` (`pipx install git+...`); binarki po stabilizacji
- [ ] Decyzja zapisana: CI = self-hosted Actions (Ubuntu x86 + RPi 5B ARM64);
      status: maszyny w przygotowaniu — do tego czasu matryca manualna

## Faza 1 — `core`: słuchacze `[ ]`

- [ ] `listeners.py`: `psutil.net_connections` → tylko `LISTEN`
- [ ] Grupowanie dual-stack (`*:port`), odrzucanie efemerycznych (§8)
- [ ] Testy `pytest`: grupowanie, filtrowanie, parsowanie

## Faza 2 — `core`: procesy + IP `[ ]`

- [ ] `procs.py`: PID → name/cmdline, `AccessDenied` jako `PID ?` (nie crash)
- [ ] `ips.py`: local IP + exit IP (z podpisem "widziane z internetu")
- [ ] Testy jednostkowe obu modułów

## Faza 3 — `core`: Docker + tunele + tagi `[ ]`

- [ ] `docker.py`: `docker ps` → `host:cont` (decyzja z Fazy 0: CLI, nie SDK)
- [ ] `cloudflared.py`: proces + `config.yml` + metryki `:20241`
- [ ] Tagi K8s warstwa 1 (decyzja z Fazy 0)
- [ ] Koniec logiki zbierania — zamrożenie API `core/`

## Faza 4 — CLI `[ ]`

- [ ] Typer + Rich: `--cli`, `--json`, `--filter`, `--kill`
- [ ] `--json` jako kontrakt (golden testy przez `typer.testing.CliRunner`)
- [ ] Kontrakt wejścia: brak flagi = TUI, `--cli` = CLI

## Faza 5 — TUI + kill `[ ]`

- [ ] Textual: `Header + Input + DataTable + Footer`, kolumny z §4.2
- [ ] Klawisze: `/` filtr, `s` sort, `r` refresh (diff co 2 s), `j` eksport, `q` quit
- [ ] Kill: klawisz `k` z potwierdzeniem + allowlista (§6) + `--kill` w CLI
- [ ] Smoke testy headless (`run_test()` / `Pilot`): start, filtr, quit

## Faza 6 — stabilizacja i release MVP `[ ]`

- [ ] Ruff + Pyrefly na czysto, `pytest` zielone
- [ ] Matryca manualna Win/Linux/Mac (do czasu gotowości runnerów)
- [ ] Release: instalacja przez `pipx`, weryfikacja `portscanner` → TUI

---

## Po MVP (kolejność orientacyjna)

1. GUI: `pywebview` + Vue, flaga `--gui` + ikonka desktopowa (osobny target builda)
2. K8s warstwa 2 (`--kube`)
3. Serwer MCP (`mcp`, `stdio`, read-only domyślnie; §12)
4. Binarki (PyInstaller) + podpisywanie
