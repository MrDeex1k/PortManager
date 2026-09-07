# PortManager — PortScanner

Lokalny skaner portów. Pokazuje, **co słucha na Twoim komputerze** — port, proces, kontener Docker, tunel.

> **Status: Fazy 0–5 ukończone.** Instalowalny pakiet zawiera odczyt lokalnych
> gniazd TCP/UDP, procesów, IP, Dockera, tuneli i tagów K8s, jednorazowe CLI
> oraz domyślny TUI z filtrem, sortowaniem, eksportem i kończeniem procesów.
> Pozostaje Faza 6: stabilizacja, matryca systemów i release MVP.

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

Filtr (`/`), sortowanie (`s`), odświeżanie co 2 s, kończenie procesu (`k`
z potwierdzeniem), eksport do JSON (`j`) i wyjście (`q`). Odczyty w tle nie
blokują nawigacji; raporty źródeł pokazują ograniczenia uprawnień.
Szczegóły: [TUI](docs/tui.md).

### CLI — do skryptów ⚙️

Jednorazowy wynik, idealny do automatyzacji:

```bash
portscanner --cli --json | jq '.[] | select(.port == 8080)'
portscanner --cli --filter :8080
portscanner --cli --kill 4123
```

`--json` wypisuje wyłącznie tablicę portów na stdout; raporty źródeł są na stderr.
Błąd podstawowego odczytu zwraca kod 1, także przy częściowych danych.
`--kill` działa po potwierdzeniu, tylko dla własnych procesów z gniazdem
na allowliście; `--force` nie omija blokad ani zgody.
Szczegóły: [CLI](docs/cli.md).

### GUI — do klikania 🖱️

Lekka aplikacja desktopowa (`pywebview` + Vue) na tym samym `core/`. Status: **po MVP**.

---

## Start

```bash
uv sync --locked
uv run portscanner --help   # działa już w Fazie 0
uv run portscanner          # interaktywny TUI
uv run portscanner --cli    # jednorazowa tabela portów
uv run portscanner --cli --json --filter :8080  # JSON dla jednego portu
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
CLI i TUI są dostępne; weryfikacja wydania na trzech systemach pozostaje w Fazie 6.

## Odczyt portów z Pythona (Faza 1)

```python
from portscanner.core.listeners import ListenerScanError, collect_listeners

try:
    for entry in collect_listeners():
        print(entry)
except ListenerScanError as error:
    print(error)
```

`collect_listeners()` zwraca `list[PortEntry]`: TCP w stanie `LISTEN` oraz
związane gniazda UDP bez zdalnego adresu. Nie wysyła pakietów. Wysokie porty
nie są odrzucane; UDP nie potwierdza obecności serwera ani handshake.
Pary wildcard IPv4/IPv6 tego samego znanego PID, protokołu i portu są
prezentowane jako `bind="*"`. `group_dual_stack=False` zachowuje osobne adresy.

Odmowa odczytu całej listy zgłasza `ListenerAccessDenied` (podklasę
`ListenerScanError`); pozostałe błędy systemowe zgłaszają `ListenerScanError`.
Brak widocznego właściciela jest reprezentowany przez `pid=None`.
Według [dokumentacji psutil](https://psutil.io/api/#psutil.net_connections)
systemowy odczyt na macOS wymaga root, a na Linuxie niedostępne połączenia mogą
zostać pominięte bez błędu. Wynik nie gwarantuje pełnej widoczności systemu.

## Procesy i adresy IP (Faza 2)

```python
from portscanner.core.listeners import collect_listeners
from portscanner.core.procs import enrich_processes
from portscanner.core.ips import collect_local_ips

ports = enrich_processes(collect_listeners())  # może zgłosić ListenerScanError
addresses = collect_local_ips()  # może zgłosić LocalIPError
```

`enrich_processes()` zwraca nowe wpisy `PortEntry` z polem `process`.
Wcześniej pole to ma wartość `None` (szczegółów jeszcze nie odczytano).
`ProcessInfo` zawiera PID, nazwę, argumenty jako tuple oraz status odczytu:
`ok`, `unknown` (brak PID), `access_denied`, `gone` lub `error`.
Odmowa odczytu argumentów nie usuwa dostępnej nazwy; zakończenie procesu
podczas odczytu usuwa częściowe szczegóły. PID odczytywany jest raz na migawkę,
bez cache między odświeżeniami. Odczyt nie jest atomowy i nie stanowi podstawy
do kill bez ponownej weryfikacji tożsamości procesu w `core/actions.py`.

`collect_local_ips()` zwraca listę `LocalIP(interface, address, family)`,
w tym loopback, VPN i link-local. Zachowuje scope IPv6 zwrócony przez OS.
Nie wybiera jednego głównego adresu i nie wykonuje żądań sieciowych.

Exit IP pobiera się **osobno i jawnie**:

```python
from portscanner.core.ips import ExitIPError, fetch_exit_ip

try:
    result = fetch_exit_ip(timeout=3.0)  # żądanie HTTPS do api64.ipify.org
    print(result.label, result.address)
except ExitIPError as error:
    print(error)
```

Etykieta wyniku to **exit IP (widziane z internetu)**. Usługa
[ipify](https://www.ipify.org/) zwraca jeden IPv4 lub IPv6 zależnie od użytej
trasy, także VPN/proxy. Zapytanie ujawnia usłudze adres wyjściowy tej trasy.
Nie oznacza to adresu routera ani dostępności portów z internetu.
Funkcja nie ponawia żądań, ogranicza odpowiedź do 64 bajtów i waliduje publiczny IP.
Timeout dotyczy operacji gniazda, nie stanowi twardego limitu całej funkcji
(w szczególności DNS); przyszły TUI powinien wykonać ją poza wątkiem renderowania.
Awaria tej usługi nie wpływa na odczyty lokalne.

## Wspólna migawka (Faza 3)

```python
from portscanner.core import collect_snapshot

snapshot = collect_snapshot()
for report in snapshot.reports:
    print(report.source, report.status)
for entry in snapshot.ports:
    print(entry)
```

Migawka łączy porty, procesy, adresy, publikacje Dockera, reguły tuneli i tagi
K8s. Błąd opcjonalnego źródła nie usuwa pozostałych danych. `origin="docker"`
oznacza publikację bez potwierdzonego gniazda; reguła tunelu nie potwierdza
publicznej dostępności hostname, a tag K8s jest heurystyką.

Docker używa wyłącznie lokalnego socketu/pipe. Odczyt tuneli może czytać lokalną
konfigurację i odpytywać metryki HTTP loopback procesu cloudflared.
`collect_snapshot(docker=False, tunnels=False)` wyłącza te źródła;
`metrics=False` pomija samo HTTP. Exit IP nadal wymaga osobnego wywołania.
Pełny kontrakt i ograniczenia: [API core](docs/core-api.md).

## Dokumentacja

| Plik | O czym |
|---|---|
| [`docs/mvp.md`](docs/mvp.md) | Pełna specyfikacja MVP: stack, decyzje, pułapki |
| [`docs/plan-mvp.md`](docs/plan-mvp.md) | Fazy realizacji z checkboxami |
| [`docs/core-api.md`](docs/core-api.md) | Kontrakt API core i ograniczenia źródeł |
| [`docs/cli.md`](docs/cli.md) | Flagi CLI, JSON, kody wyjścia i polityka kończenia procesów |
| [`docs/tui.md`](docs/tui.md) | Skróty TUI, odświeżanie, eksport JSON i dialog kończenia procesu |
| [`docs/conventional-commits.md`](docs/conventional-commits.md) | Format commitów + hooki |

## Status

Fazy 0–5 ukończone; następna jest Faza 6 — stabilizacja i release MVP.
Plan w [`docs/plan-mvp.md`](docs/plan-mvp.md). CI na self-hosted Actions
(Ubuntu x86 + RPi 5B ARM64) czeka na przygotowanie maszyn; do tego czasu
obowiązuje weryfikacja manualna. Testy tego etapu wykonano na macOS / Python 3.13:
231 zaliczonych, 1 systemowy test integracyjny pominięty z powodu uprawnień.
Test rzeczywistych gniazd własnego procesu z odczytem nazwy/argumentów jest zaliczony.
Odczyt lokalnych interfejsów także sprawdzono na żywo. Exit IP sprawdzono
na podstawionych odpowiedziach HTTP oraz pojedynczym żądaniem HTTPS do ipify
za zgodą użytkownika (2026-09-07): poprawny IPv4, bez zapisywania adresu.
Testy integracyjne
wymagają możliwości tworzenia gniazd loopback w środowisku uruchomienia.

Licencja: [GPLv3](LICENSE) © 2026 Jakub Batycki.
