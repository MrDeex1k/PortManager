# Rozwój i testy

## Środowisko

Repozytorium używa uv i lockfile'a Pythona. Wersję interpretera do developmentu
określa [.python-version](../.python-version); minimalne wymagania runtime
znajdują się w [pyproject.toml](../pyproject.toml).

Z katalogu głównego:

```bash
uv sync --locked
```

Dla developmentu desktopowego:

```bash
uv sync --locked --extra gui
cd frontend
bun install --frozen-lockfile
cd ..
```

Bun powinien odpowiadać `packageManager` w [package.json](../frontend/package.json).
Kontrola typów Vue używa Node; Vite i testy frontendu działają pod Bun.
[Podgląd Vite i mostek desktopowy](gui.md#podgląd-i-development).

## Kontrole lokalne

Z katalogu głównego repozytorium:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyrefly check
uv run --locked pytest -q -rs
```

Po instalacji zależności frontendu, w katalogu `frontend`:

```bash
bun run format:check
bun run test
bun run build
```

`bun run build` uruchamia także vue-tsc. Samą kontrolę typów wykonuje
`bun run check`. Testy nie wymagają budowania frontendu, ale natywne GUI
korzysta z gotowych zasobów Vite.

## Zakres testów

- **Core:** modele, scalanie źródeł, mapowania Docker i tuneli, Kubernetes,
  filtry, maskowanie argumentów oraz reguły operacji na procesach.
- **CLI:** kontrakt JSON, stdout/stderr, kody wyjścia, walidacja argumentów
  oraz potwierdzanie i odmowa operacji.
- **TUI:** Textual Pilot sprawdza skróty, filtrowanie, sortowanie, aktualizacje
  wierszy, eksport i dialogi przy odczytach w tle.
- **GUI:** testy mostka obejmują serializację, filtrowanie, eksport,
  współbieżność, weryfikację celu i jednorazowość zgody.
- **Integracje lokalne:** gniazda loopback, interfejsy, HTTP loopback i operacje
  na tymczasowym procesie utworzonym przez test, powolne odpowiedzi HTTP,
  odczyt FIFO i sprzątanie potomków poleceń.

Testy integracyjne wymagają możliwości tworzenia gniazd loopback.
Część testów zależy od systemu i uprawnień; powody pominięć pokazuje `pytest -rs`.
Test projekcji Kubernetes używa zainstalowanego `kubectl`, tymczasowego kubeconfig
i serwera API na loopback; bez kubectl zostaje pominięty. Nie kontaktuje się
z klastrem użytkownika.
Kontrolowane odpowiedzi Docker, tuneli i kubectl sprawdzają kontrakty, ale
nie zastępują pełnej weryfikacji na wszystkich systemach i wdrożeniach usług.

Natywny smoke GUI na macOS, po synchronizacji dodatku `gui` i buildzie frontendu:

```bash
uv run --locked --extra gui python scripts/smoke_gui.py
```

Skrypt otwiera okno, używa kontrolowanej migawki i tymczasowego procesu Pythona
z lokalnym gniazdem. Sprawdza m.in. responsywność, eksport, dialogi i zakończenie
tego procesu przez standardowe reguły core. Nie dowodzi pełnej widoczności gniazd
systemowych. Weryfikacja instalacji wheel: [pakowanie](release.md#weryfikacja-artefaktu).

## Zależności

Zależności i wybrane wersje są zapisane w manifestach oraz `uv.lock` i `bun.lock`.
Instalacja odtwarzająca środowisko używa `--locked` i `--frozen-lockfile`.

Aktualizacja wersji:

```bash
uv lock --upgrade
cd frontend
bun update --latest --exact
```

Konfiguracje uv i Bun stosują karencję publikacji nowych wersji wynoszącą
3 godziny. uv wyklucza wydania prerelease. TypeScript jest przypięty do wersji
zgodnej z vue-tsc; zmianę tych zależności sprawdza kontrola typów, build i smoke GUI.

## Commity i hooki

Po zainstalowaniu Lefthook uruchom `lefthook install` z katalogu repozytorium.
Hooki sprawdzają format commitów i Ruff; pełny zestaw powyższych kontroli
uruchamia się osobno. [Format Conventional Commits](conventional-commits.md).

## Kontrakty modeli i mostka

Po zmianie modeli core lub `portscanner/gui/contracts.py` wygeneruj typy:

```bash
uv run --locked python scripts/generate_contracts.py
```

Generator wymaga zainstalowanych narzędzi developmentu Python i frontendu.
Test `tests/test_contracts.py` sprawdza brak rozbieżności. Bez Bun lub
`frontend/node_modules` zostaje pominięty z powodem widocznym przez `pytest -rs`.
Przed połączeniem zmian wykonaj pełną kontrolę po instalacji zależności frontendu:

```bash
cd frontend
bun install --frozen-lockfile
cd ..
uv run --locked python scripts/generate_contracts.py --check
uv run --locked pytest -q -rs tests/test_contracts.py
```

Nie edytuj ręcznie
`core_payloads.py`, `contracts.generated.ts` ani tabeli Unicode `casefold.ts`. Przypadki filtrów Python/TypeScript
są współdzielone w `tests/fixtures/filter_cases.json`.

Smoke eskalacji w natywnym GUI na macOS (własny proces zamyka port po SIGTERM):

```bash
uv run --locked --extra gui python scripts/smoke_gui.py --escalation
```
