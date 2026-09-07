# GUI — prototyp desktopowy

**Faza 7.1 zakończona 2026-09-08:** szkielet pywebview i interaktywny prototyp Vue. Dane w GUI są
**wyłącznie przykładowe**. Nie wykonujemy odczytu systemu, zapytań o exit IP
ani operacji na procesach. CLI i TUI zachowują dotychczasowe działanie.

## Uruchomienie

W katalogu repozytorium:

```bash
uv sync --locked --extra gui
cd frontend
bun install --frozen-lockfile
bun run build
cd ..
uv run --locked --extra gui portscanner --gui
```

`--gui` nie łączy się z flagami CLI. Bez flag nadal uruchamia się TUI.
Brak pywebview lub zasobów powoduje czytelny komunikat na stderr i kod 1.
Samo CLI/TUI nie potrzebuje pywebview, Bun ani Node.

## Development z Vite

Pierwszy terminal, w `frontend/`:

```bash
bun run dev
```

Podgląd w przeglądarce: <http://127.0.0.1:5173>.
Drugi terminal, w katalogu repozytorium:

```bash
PORTSCANNER_GUI_DEV_URL=http://127.0.0.1:5173 uv run --locked --extra gui portscanner --gui
```

Vite nasłuchuje tylko na `127.0.0.1`, z `strictPort`. Mostek akceptuje wyłącznie
ten konkretny URL deweloperski. Zbudowane GUI korzysta z zasobów lokalnych
i serwera statycznego pywebview; nie potrzebuje działającego Vite.
Serwery nie odpytują zewnętrznych usług. Fonty systemowe, ikony i kod
aplikacji są lokalne.

## Narzędzia i zgodność

Wersje sprawdzono przez Context7 oraz rejestry npm/PyPI 2026-09-08.
Dokładne wersje zapisano w `package.json`, `bun.lock` i `uv.lock`.

| Narzędzie | Wersja | Rola |
|---|---|---|
| Bun | 1.4.2 | Instalacja, runner skryptów, runtime Vite i testów |
| Vue | 3.5.42 | Interfejs i reaktywność |
| TanStack Table | 9.2.4 | Tabela i sortowanie, API `useTable` v9 |
| TanStack Vue Query | 5.102.8 | Stan i błędy połączenia z mostkiem |
| Vite / plugin Vue | 8.2.2 / 6.0.8 | HMR oraz budowanie lokalnych zasobów |
| Tailwind / plugin Vite | 4.3.3 / 4.3.3 | CSS przez `@tailwindcss/vite` i `@import "tailwindcss"` |
| pywebview | 6.2.1 | Okno i natywny WebKit na macOS |
| TypeScript / vue-tsc | 6.0.3 / 3.3.11 | Kontrola typów kodu i szablonów Vue |
| Prettier | 3.9.6 | Formatowanie frontendu |

Nie ma konfiguracji PostCSS ani Autoprefixera. Vite może mieć PostCSS w swoim
drzewie zależności; aplikacja nie konfiguruje go do Tailwinda.

**Wyjątek dla kontroli typów:** `bun run check` uruchamia `vue-tsc` przez Node.
Sprawdzono Node 26.5.0; zalecany Node >=22.12. TypeScript 7.0.2 nie udostępnia
`typescript/lib/tsc`, którego potrzebuje vue-tsc. Pod Bun 1.4.2 mechanizm
vue-tsc/Volar oparty na przechwyceniu odczytu kompilatora nie obsługuje `.vue`
poprawnie. TypeScript 6.0.3 + Node przechodzi pełną kontrolę szablonów,
bez zastępowania komponentów deklaracjami `any`. Vite dev/build działa pod Bun.

Dokumentacja: [Vue](https://vuejs.org/guide/introduction.html),
[TanStack Table v9](https://tanstack.com/table/latest/docs/framework/vue/guide/sorting),
[Vue Query](https://tanstack.com/query/latest/docs/framework/vue/installation),
[Tailwind z Vite](https://tailwindcss.com/docs/installation/using-vite),
[Vite](https://vite.dev/guide/), [pywebview](https://pywebview.flowrl.com/guide/).

## Co można sprawdzić w prototypie

- Filtry wszystkich wpisów, publikacji Docker i reguł tuneli oraz TCP/UDP.
- Wyszukiwanie tekstowe, dokładne `:PORT` i `pid:PID` na przykładowej migawce.
- Sortowanie przez nagłówki; kliknięcie numeru portu otwiera szczegóły.
- Bind, PID, przykładowe polecenie, mapowanie kontenera i reguła tunelu.
- Kopiowanie adresu z obsługą odmowy dostępu do schowka.
- Pusty wynik z resetem filtrów, zamknięcie inspektora oraz dialog informacji.
- `/` lub Cmd/Ctrl+K ustawia fokus wyszukiwania; Escape czyści wyszukiwanie,
  zamyka panel albo natywny dialog. Obsługiwane `prefers-reduced-motion`.
- Eksport przykładu w przeglądarce: `portmanager-preview.json`, w aktualnej
  kolejności i z aktywnymi filtrami. To **format prototypu**, nie kontrakt
  `PortEntry[]` CLI/TUI. Natywny zapis pliku należy do Fazy 7.4.
  Przycisk eksportu w oknie desktopowym jest na tym etapie nieaktywny.

Paleta zaakceptowana przez użytkownika: grafit i stonowany błękit z nutą
lawendy (`#a9b8f5`), bez zieleni i poświaty. Wąskie okno przenosi inspektor
pod tabelę. Przy desktopowej szerokości lista i inspektor przewijają się osobno.
[Ikona i źródło projektu](brand/README.md).

## Granica prototypu

`frontend/src/preview.ts` zawiera jawnie nazwany model `PreviewPort` i fixture.
Filtr prototypu nie jest implementacją kontraktu core. W Fazie 7.2 trzeba
zastąpić to adapterem do modeli i filtrów Pythona, bez utrzymywania drugiej
logiki odczytu. Mostek `DesktopAPI` udostępnia obecnie tylko `get_app_info`.
Wykrycie `pywebviewready` aktywuje ponowne pobranie metadanych przez Query;
brak mostka w przeglądarce jest poprawnym trybem podglądu.

Fazy 7.2–7.5 pozostają otwarte: rzeczywiste migawki, raporty źródeł,
odświeżanie, eksport z dialogiem systemowym i operacje przez `core/actions`.
Pełna dystrybucja `.app`, podpisywanie i Windows/Linux nie są częścią prototypu.

## Następny etap — 7.2

Podłączamy rzeczywiste dane z `core/`, zachowując zaakceptowany wygląd i ikonę.
Adapter mostka ma korzystać z `collect_snapshot()` oraz wspólnych modeli
i filtrów Pythona. TanStack Query obsłuży cykl odczytu, a Table prezentację
i sortowanie. Odczyty w tle i odświeżanie co 2 s muszą zachowywać zaznaczenie
oraz odrzucać nieaktualne wyniki.

Priorytet na macOS: raport odmowy dostępu zamiast pozornie pustej listy portów.
Widok ma rozróżniać ładowanie, brak wpisów, brak dopasowań i częściowe dane.
Bez automatycznego podnoszenia uprawnień ani zapytań o exit IP.
Pełna lista warunków znajduje się w [planie 7.2](plan-mvp.md).
Potem: kompletność widoku i szczegółów (7.3), eksport zgodny z CLI/TUI
i operacje przez `core/actions` z potwierdzeniem (7.4), weryfikacja całości (7.5).

## Weryfikacja zamknięcia 7.1

Wykonano 2026-09-08 na macOS ARM64. Wyniki dotyczą szkieletu i prototypu,
nie gotowego GUI z rzeczywistymi danymi.

| Kontrola | Wynik |
|---|---|
| Ruff lint i format | Bez błędów |
| Pyrefly | 0 błędów, 12 ostrzeżeń |
| Pełny pytest, Python 3.13.9 | 253 zaliczone, 1 pominięty |
| Testy wejścia GUI po integracji ikony | 22 zaliczone |
| Bun | 3 testy zaliczone, 11 asercji |
| Vue typecheck, Prettier, Vite build | Zaliczono |
| Przeglądarka | Sortowanie, filtry źródła/PID/UDP, zaznaczenie, pusty wynik, reset, dialog i eksport przykładu |
| Układ | Sprawdzono 1320 × 860, 900 × 620 oraz 390 × 844; brak poziomego przepełnienia strony mobilnej |
| Natywny WebKit przez pywebview | Vue, metadane mostka, filtr, załadowanie ikony i zamknięcie testowego okna |
| sdist i wheel | Zasoby Vue i ICNS w pakiecie, bez `node_modules` |
| Wheel poza repozytorium | Instalacja w oddzielnym tymczasowym venv; smoke GUI i `--help` zaliczone |

Pominięcie pytest dotyczy systemowego odczytu `psutil.net_connections()`,
który wymaga dodatkowych uprawnień OS. Testy integracyjne własnych gniazd
wykonano poza sandboxem blokującym loopback. To nie jest dowód pełnego
odczytu portów macOS bez uprawnień.

Pakiet prototypu zbudowano osobno w `dist/gui-preview/`, zachowując wcześniejsze
artefakty MVP. Test instalacji GUI używał tymczasowego venv i wheel z dodatkiem
`[gui]`; nie był nową matrycą pipx z Fazy 6. Nie opublikowano taga ani release.
Nie zweryfikowano jeszcze skrótu `.app`, natywnego eksportu, operacji procesów
w GUI, Windows ani Linux.

## Kontrole i pakowanie

```bash
# w frontend/
bun run format:check
bun run build
bun test

# w katalogu repozytorium
uv run --locked --extra gui ruff check .
uv run --locked --extra gui ruff format --check .
uv run --locked --extra gui pyrefly check
uv run --locked --extra gui pytest -q -rs
uv run --locked --extra gui python scripts/smoke_gui.py
uv build
```

Smoke GUI wymaga sesji graficznej: otwiera okno, czeka na Vue i mostek,
sprawdza filtr i ikonę, następnie zamyka własne okno. Nie wykonuje odczytów portów.

`bun run build` zapisuje zasoby w `portscanner/gui/assets/`. Hatch dołącza je
do sdist i wheel, mimo że są ignorowane przez Git. **Najpierw build frontendu,
potem `uv build`**. Nie budujemy frontendu automatycznie przy instalacji pakietu
Python. Wheel bez zasobów nadal obsługuje CLI/TUI i zgłasza ich brak przy `--gui`.
Nie publikuj wheel GUI bez wcześniejszego builda. `node_modules` nie wchodzi
do dystrybucji. Plik `.icns` znajduje się w pakiecie Python.

Instalacja zbudowanego wheel: `pipx install './dist/portscanner-0.1.0-py3-none-any.whl[gui]'`.
Wywołaj `portscanner --gui` spoza repozytorium, aby sprawdzić zasoby pakietu.
