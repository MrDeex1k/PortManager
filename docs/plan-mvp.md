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

## Faza 1 — `core`: słuchacze `[x]`

- [x] Kontrakt: `collect_listeners(*, group_dual_stack=True) -> list[PortEntry]`;
      błędy odczytu jako `ListenerScanError`, odmowa dostępu jako jego podklasa
      `ListenerAccessDenied`, bez udawania pustej listy i bez podnoszenia uprawnień.
- [x] `listeners.py`: `psutil.net_connections(kind="inet")` → TCP tylko `LISTEN`;
      UDP: związane gniazdo bez zdalnego adresu, nie potwierdzony serwer.
- [x] Mapowanie IPv4/IPv6, zachowanie scope IPv6 i `pid=None`, pomijanie
      gniazd niezwiązanych, portu 0 i nieobsługiwanych rodzin/typów.
- [x] Filtrowanie po stanie/rodzaju gniazda, nie po numerze portu:
      serwery na portach 49152–65535 pozostają widoczne.
- [x] Grupowanie wyłącznie par `0.0.0.0` + `::` z tym samym znanym PID,
      protokołem i portem jako `bind="*"`; opcja wyłączenia grupowania.
      Usuwanie identycznych wpisów i stabilna kolejność wyników.
- [x] Testy jednostkowe filtrowania, adresów, grupowania, kolejności i błędów;
      test integracyjny prawdziwych gniazd TCP/UDP.

Weryfikacja (macOS / Python 3.13): 35 testów zaliczonych, 1 pominięty
(systemowy odczyt wymaga dodatkowych uprawnień). Test własnego procesu używa
rzeczywistych danych `psutil.Process().net_connections()` i podstawia jedynie
źródło odczytu; nie jest dowodem pełnego odczytu systemowego. Ruff lint + format
bez błędów, Pyrefly 0 błędów. Pełna matryca systemów pozostaje w Fazie 6.

## Faza 2 — `core`: procesy + IP `[x]`

- [x] Procesy: `read_process(pid) -> ProcessInfo` z nazwą, argumentami i statusem
      odczytu (`ok`, `unknown`, `access_denied`, `gone`, `error`). Zachowanie
      dostępnych pól przy częściowej odmowie dostępu. Brak PID nie odpytuje
      własnego procesu. Zniknięcie / wykryte ponowne użycie PID usuwa szczegóły.
- [x] Wzbogacanie: `enrich_processes(entries) -> list[PortEntry]`, pole `process`,
      bez mutowania wejścia; każdy PID odczytywany raz na wywołanie, bez cache
      między migawkami. Odczyt portów i procesów nie jest atomowy.
- [x] Lokalne IP: `collect_local_ips() -> list[LocalIP]`, interfejs + IPv4/IPv6,
      także loopback/VPN/link-local, scope IPv6, deduplikacja i stabilna kolejność.
      Bez DNS/HTTP; błędy jako `LocalIPError`.
- [x] Exit IP: osobne `fetch_exit_ip(timeout=3.0) -> ExitIP`, HTTPS do
      `api64.ipify.org`, IPv4 lub IPv6, etykieta `exit IP (widziane z internetu)`.
      Tylko jawne wywołanie, timeout operacji gniazda, bez retry, limit 64 bajtów,
      walidacja publicznego adresu i błędy jako `ExitIPError`.
- [x] Testy obu modułów: uprawnienia, znikające procesy, granice argumentów,
      cache migawki, adresy interfejsów, brak sieci, timeout, HTTP i błędne dane.
      Integracja prawdziwych portów z procesem oraz odczyt lokalnych interfejsów.

Weryfikacja (macOS / Python 3.13): 83 testy zaliczone, 1 systemowy test
integracyjny pominięty z powodu uprawnień; Ruff lint + format bez błędów,
Pyrefly 0 błędów. Testy HTTP używają kontrolowanych odpowiedzi. Dodatkowo
2026-09-07, za zgodą użytkownika, wykonano pojedyncze żądanie HTTPS do ipify:
poprawny IPv4 i etykieta, bez zapisywania adresu ani ponawiania żądania.
Pełna matryca systemów nadal w Fazie 6.

## Faza 3 — `core`: Docker + tunele + tagi `[x]`

- [x] Modele: `SourceReport`, `Collection`, `DockerPort`, `TunnelInfo`,
      `TunnelRoute`, `ServiceTag`, `Snapshot`; pochodzenie wiersza socket/docker.
- [x] Docker CLI: lista `ps`, strukturalne mapowania przez projekcję `inspect`,
      etykiety Compose, IPv4/IPv6 i TCP/UDP. Lokalny socket/pipe, timeouty,
      obsługa braku CLI, daemona, znikających kontenerów i błędnych danych.
- [x] Cloudflared: wykrywanie procesu, jawny/domniemany config YAML i tryb
      tokenowy; dopasowanie lokalnych origin bez DNS. Metryki wyłącznie
      na loopback przypisanym do PID, bez proxy/przekierowań, z limitami.
- [x] Tagi K8s/K3s/MicroK8s warstwa 1: proces lub typowy port z jawną podstawą
      heurystyki, bez kubectl i dostępu do klastra.
- [x] Wspólna migawka `collect_snapshot()`: niezależne raporty źródeł,
      mapowania Docker bez gniazda oznaczone `origin="docker"`, opcje wyłączenia
      źródeł, bez automatycznego exit IP i bez zmian usług.
- [x] Testy parserów, błędów, dopasowania adresów/protokołów, transportu HTTP
      loopback i serializacji. API dla CLI/TUI opisane w `docs/core-api.md`.

Weryfikacja (macOS/Python 3.13): 146 testów zaliczonych, 1 pominięty
(systemowy odczyt gniazd wymaga dodatkowych uprawnień); Ruff lint + format
bez błędów, Pyrefly 0 błędów. Lokalny Docker odpowiada, bez opublikowanych
mapowań; brak działających tuneli. Przypadki mapowań/Compose/konfiguracji
sprawdzone na danych testowych; rzeczywisty transport metryk na HTTP loopback.
Szczegóły i ograniczenia w `docs/core-api.md`. Matryca systemów nadal w Fazie 6.

## Faza 4 — CLI `[x]`

- [x] Typer + Rich: `--cli`, tabela, `--json`, `--filter`, `--kill`.
- [x] Kontrakt JSON: tablica PortEntry na stdout; raporty na stderr.
      Golden test przez CliRunner, kody wyjścia i błędy opisane w `docs/cli.md`.
- [x] Filtry współdzielone w core: dokładne `:PORT`, `pid:PID` i tekst bez
      rozróżniania wielkości liter; walidacja przed odczytem systemu.
- [x] Wyłączanie źródeł i metryk, timeout, `--no-color`, jawny `--exit-ip`
      wyłącznie w trybie tabeli, bez automatycznego żądania do internetu.
- [x] `--kill`: wspólny core/actions z allowlistą, ochroną PID/infrastruktury,
      sprawdzeniem właściciela i gniazd, potwierdzeniem i ponowną weryfikacją
      danych procesu. `--force` tylko do eskalacji po timeout, bez omijania zgody.
- [x] Kontrakt wejścia: `--cli` uruchamia CLI, brak flagi wybiera gałąź TUI;
      do Fazy 5 ta gałąź jasno informuje o niedostępności (kod 1), bez skanowania.

Weryfikacja: 214 testów zaliczonych, 1 pominięty (uprawnienia macOS), Ruff
lint + format bez błędów, Pyrefly 0 błędów. Test rzeczywistego terminate dotyczył
wyłącznie tymczasowego procesu utworzonego przez test. Zainstalowana komenda
zwraca poprawny JSON, stderr i kod błędu przy odmowie systemowego odczytu.

## Faza 5 — TUI + kill `[x]`

- [x] Domyślny Textual: `Header + Input + DataTable + Footer`, kolumny z §4.2,
      dodatkowo TAG/ŹRÓDŁO, lokalne IP, czas odczytu i raporty źródeł.
- [x] `/` filtr, `s` sortowanie liczbowe po porcie lub tekstowe po procesie,
      `r` odczyt, `q` wyjście; Enter/Esc przywracają fokus tabeli.
- [x] Timer co 2 s i odczyty w tle bez nakładania. Diff wierszy/komórek zachowuje
      zaznaczenie; klucz rozszerzony o PID i origin rozróżnia współdzielone porty.
- [x] `j` zapisuje widoczną, posortowaną migawkę do nowego pliku JSON w cwd,
      bez nadpisania, z raportem wyniku; na POSIX prawa 0600.
- [x] `k` i dialog zgody korzystają z `core/actions.py`: domyślne anulowanie,
      jawny force, niezmienny cel potwierdzenia, ponowna weryfikacja w core,
      brak blokowania UI podczas operacji i obsługa odmów/błędów.
- [x] Testy `run_test()` / Pilot: start, filtr, sort, quit, diff, timer,
      błędy źródeł, eksport, anulowanie/zgoda/force i wolna operacja procesu.
      Wspólne formatowanie CLI/TUI w `presentation.py`; core bez importów UI.
- [x] Dokumentacja PL w `docs/tui.md`, README oraz aktualizacja kontraktów.

Weryfikacja: 231 testów zaliczonych, 1 pominięty (uprawnienia macOS), Ruff
lint + format bez błędów, Pyrefly 0 błędów. Komenda bez flag uruchomiona
w terminalu PTY: działający TUI z raportami ograniczeń, wyjście przez `q` z kodem 0.
Testy TUI używają kontrolowanych danych i nie kończą istniejących procesów.
Zbudowano sdist i wheel; sprawdzono obecność modułów TUI w wheel.
Matryca systemów i wydanie przez pipx pozostają w Fazie 6.

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
