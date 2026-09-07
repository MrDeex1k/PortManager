# Plan MVP — fazy

Stan na 2026-09-07. Źródło decyzji: `docs/mvp.md`.

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

## Faza 0 — fundament repo `[x]`

- [x] Decyzje MVP z §9 zatwierdzone; MCP pozostaje poza MVP.
      `uv lock --upgrade --prerelease disallow` (2026-09-07): bez zmian wersji;
      psutil 7.2.2, PyYAML 6.0.3, Textual 8.2.8, Typer 0.27.2,
      Ruff 0.16.6, Pyrefly 1.2.0, pytest 9.1.1.
- [x] Zacommitować fundament repo (`LICENSE`, `lefthook.yml`, `scripts/`, `docs/`)
- [x] `lefthook install`: lokalne `commit-msg` i `pre-commit`.
      Zgodnie z `conventional-commits.md` zdalna walidacja formatu nie jest wymagana
      w przyjętym wariancie bez Actions. Stary wymóg rulesetu zastąpiono tą decyzją.
      Odczyt GitHub API 2026-09-07: brak rulesetów; ochrona historii opisana
      w dokumentacji jest instrukcją konfiguracji, a nie wdrożonym zabezpieczeniem.
- [x] `pyproject.toml` z entry `portscanner`, `.python-version=3.13`,
      pakiet `portscanner/` i backend Hatchling; komenda `--help` działa.
- [x] Zależności runtime i dev zapisane w `pyproject.toml` i `uv.lock`; `uv sync`
- [x] Ruff jako blokujący `pre-commit` w `lefthook.yml`
- [x] Szkielet `portscanner/core/model.py` (`PortEntry`) + pierwszy test `pytest`
- [x] Decyzja zapisana: dystrybucja MVP = `pipx` (`pipx install git+...`); binarki po stabilizacji
- [x] Decyzja zapisana: CI = self-hosted Actions (Ubuntu x86 + RPi 5B ARM64);
      status: maszyny w przygotowaniu — do tego czasu matryca manualna

Weryfikacja Fazy 0 (macOS, Python 3.13): Ruff lint + format bez błędów,
Pyrefly 0 błędów, pytest 1 test zaliczony; zbudowano sdist i wheel z tego sdist.
Wheel zainstalowano w oddzielnym środowisku i uruchomiono spoza repo:
`--help` zwraca 0, brak flag i `--cli` zwracają 1 z jawnym komunikatem
o niezaimplementowanym interfejsie. Walidator commitów akceptuje poprawny
temat i odrzuca błędny. Pełna matryca systemów pozostaje w Fazie 6.

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
