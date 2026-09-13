# GUI desktopowe

**Stan 2026-09-12:** Faza 7 jest zakończona na macOS. GUI korzysta z tego
samego `core/` co CLI i TUI. Tryb desktopowy pokazuje rzeczywiste dane;
otwarcie samego Vite w przeglądarce używa jawnych danych demonstracyjnych.

## Uruchomienie

```bash
uv sync --locked --extra gui
cd frontend
bun install --frozen-lockfile
bun run build
cd ..
uv run --locked --extra gui portscanner --gui
```

`--gui` nie łączy się z flagami CLI. Bez flag uruchamia się TUI. Zależność
pywebview jest opcjonalna, więc CLI i TUI nie wymagają środowiska graficznego,
Bun ani Node.

## Skrót PortManager.app

Po instalacji wheel z dodatkiem GUI utwórz lekki bundle wskazujący polecenie
z tego środowiska:

```bash
portscanner-macos-app \
  --command "$(command -v portscanner)" \
  --output "$HOME/Applications/PortManager.app"
open "$HOME/Applications/PortManager.app"
```

Generator odmawia zastąpienia istniejącej ścieżki. Bundle zawiera ikonę ICNS,
`Info.plist` oraz mały launcher wykonujący dokładnie `portscanner --gui`.
Nie kopiuje interpretera ani zależności, więc wskazane środowisko musi pozostać
w tym samym miejscu. Bundle nie jest podpisany; samodzielna binarka,
notaryzacja i podpisywanie należą do późniejszego etapu dystrybucji.

Podczas pracy z Vite uruchom dwa terminale:

```bash
cd frontend && bun run dev
PORTSCANNER_GUI_DEV_URL=http://127.0.0.1:5173 uv run --locked --extra gui portscanner --gui
```

Mostek akceptuje wyłącznie ten adres loopback i stały port. Zbudowana aplikacja
ładuje lokalne zasoby pakietu i nie potrzebuje Vite. Nie odpytuje automatycznie
usług exit IP i nie podnosi uprawnień.

## Funkcje

- Migawka z `collect_snapshot()`: TCP/UDP, procesy, lokalne IP, Docker/Compose,
  tunele, tagi oraz raport każdego źródła.
- Odświeżanie co 2 sekundy przez TanStack Query. Odczyty nie nakładają się,
  starsza odpowiedź nie zastępuje nowszej, a zaznaczenie jest zachowywane po
  stabilnym kluczu `(proto, bind, port, pid, origin)`.
- Wyszukiwanie tekstowe oraz dokładne `:PORT` i `pid:PID` przez wspólny filtr
  Pythona. Filtry źródła i protokołu oraz sortowanie są stanem prezentacji.
- Tabela i inspektor pokazują bind, PID, stan i argumenty procesu, mapowania
  kontenerów, projekt/usługę Compose, trasy tuneli, tagi i ograniczenia danych.
- Osobne stany pierwszego odczytu, pustej migawki, braku dopasowań, danych
  częściowych i błędu. Odmowa uprawnień jest raportem, a nie pustą listą.
- Natywny eksport widocznych wierszy w bieżącej kolejności. JSON ma ten sam
  kontrakt `PortEntry[]` co CLI i TUI; systemowy dialog obsługuje wybór ścieżki
  i potwierdzenie zastąpienia istniejącego pliku.
- Kończenie procesu jest dwuetapowe. `prepare_kill()` tworzy jednorazową,
  krótkotrwałą zgodę na pokazany cel. Dialog domyślnie anuluje, osobno zezwala
  na wymuszenie po timeout, a `terminate_target()` ponownie sprawdza tożsamość,
  właściciela, allowlistę, przestrzenie nazw i lokalne gniazdo.

Metody mostu są wywoływane asynchronicznie przez pywebview poza wątkiem WebKit.
Blokady po stronie Pythona zapobiegają równoległym skanom i podwójnym operacjom.
Zmiana zaznaczenia podczas dialogu nie zmienia zapamiętanego celu zgody.
Komunikaty polityki, zniknięcie procesu i timeout wracają do interfejsu bez
automatycznej eskalacji uprawnień.

## Wygląd i narzędzia

Paleta zaakceptowana dla prototypu pozostaje bez zmian: grafit i stonowany
błękit z nutą lawendy (`#a9b8f5`). Układ opiera się na gęstej tabeli i bocznym
inspektorze. Przy węższym oknie inspektor przechodzi pod tabelę.
[Ikona i źródło projektu](brand/README.md).

| Narzędzie | Wersja | Rola |
|---|---:|---|
| Bun | 1.4.2 | instalacja, Vite i testy |
| Vue | 3.5.42 | interfejs |
| TanStack Table / Vue Query | 9.2.4 / 5.102.8 | tabela, sortowanie i cykl odczytu |
| Vite / plugin Vue | 8.2.2 / 6.0.8 | development i build |
| Tailwind / plugin Vite | 4.3.3 / 4.3.3 | stylowanie bez konfiguracji PostCSS |
| pywebview | 6.2.1 | natywne okno i dialog zapisu |
| TypeScript / vue-tsc | 6.0.3 / 3.3.11 | kontrola typów |

`bun run check` uruchamia vue-tsc przez Node z powodu zgodności Volar;
Vite i testy działają pod Bun. Wersje są przypięte w `package.json`, `bun.lock`
i `uv.lock`.

## Kontrole

```bash
cd frontend
bun run format:check
bun run check
bun test
bun run build

cd ..
uv run --locked --extra gui ruff check .
uv run --locked --extra gui ruff format --check .
uv run --locked --extra gui pyrefly check
uv run --locked --extra gui pytest -q -rs
```

Testy mostu obejmują serializację i kolejność, wspólne filtry, wolny odczyt,
błąd kolektora, eksport, redakcję sekretów, odmowę polityki i jednorazowość
zgody.

## Zamknięcie Fazy 7.5

Weryfikację wykonano 2026-09-12 na macOS ARM64:

| Kontrola | Wynik |
|---|---|
| Natywny WebKit | start, render Vue, mostek i poprawne zamknięcie |
| Responsywność | licznik WebKit działał podczas wolnego skanu i operacji procesu |
| Dane i interakcje | raport częściowy, filtr, sortowanie, odświeżenie, trwałość zaznaczenia i szczegóły |
| Eksport | widoczny posortowany `PortEntry[]`, zapis i odczyt JSON |
| Proces | domyślne force wyłączone, anulowanie bez skutku, potwierdzenie zakończyło własny proces z gniazdem |
| Wheel poza repo | CLI, TUI i pełny smoke GUI zaliczone w odizolowanym venv |
| Zawartość wheel | Vue JS/CSS/HTML, PNG i ICNS obecne |
| Skrót macOS | `Info.plist` poprawny, ICNS rozpoznany, start przez LaunchServices i standardowy Quit |
| Python | Ruff i format bez błędów; Pyrefly 0 błędów; pytest 285 zaliczonych, 1 pominięty |
| Frontend | Prettier, vue-tsc, 3 testy Bun i produkcyjny build Vite zaliczone |

Kontrolowany proces testowy jest własnym procesem Pythona z lokalnym gniazdem.
Przechodzi tę samą politykę `prepare_kill`/`terminate_target` co rzeczywiste
użycie; smoke nie omija allowlisty ani ponownej weryfikacji. Systemowy odczyt
macOS nadal może wymagać dodatkowych uprawnień i jest jawnie raportowany.
Windows/Linux, podpisywanie oraz samodzielne binarki nie były w zakresie Fazy 7.

`bun run build` zapisuje zasoby w `portscanner/gui/assets/`. Najpierw zbuduj
frontend, potem wheel przez `uv build`; `node_modules` nie trafia do pakietu.
