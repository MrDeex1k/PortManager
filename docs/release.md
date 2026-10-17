# Instalacja i pakowanie

PortManager można uruchomić ze źródeł lub zainstalować z lokalnego wheel.
CLI i TUI działają w środowisku Pythona; desktop wymaga dodatku `gui`
oraz zbudowanych zasobów frontendu. Repozytorium nie dostarcza samodzielnego,
podpisanego instalatora ani opublikowanego pakietu PyPI.

## Wymagania

- Python **3.12+** i [uv](https://docs.astral.sh/uv/).
- Do budowania GUI: Bun zgodny z `packageManager` w
  [frontend/package.json](../frontend/package.json) oraz Node do uruchamiania vue-tsc.
- Do odpowiednich integracji: lokalny Docker, cloudflared lub kubectl.
  Niedostępność integracji jest raportowana i nie usuwa danych pozostałych źródeł.

## Uruchomienie ze źródeł

```bash
git clone https://github.com/MrDeex1k/PortManager.git
cd PortManager
uv sync --locked
uv run --locked portscanner
```

Bez flag uruchamia się TUI; `--cli` wybiera jednorazowy odczyt.
Pełne polecenia: [CLI](cli.md) · [TUI](tui.md).

Do desktopu doinstaluj dodatek i zbuduj frontend:

```bash
uv sync --locked --extra gui
cd frontend
bun install --frozen-lockfile
bun run build
cd ..
uv run --locked --extra gui portscanner --gui
```

## Budowanie pakietu

Komenda `uv build` tworzy sdist i wheel w `dist/`. Dla CLI/TUI wystarczy środowisko
Pythona. Pełny pakiet z GUI wymaga wcześniejszego builda Vite:

```bash
uv sync --locked --extra gui
cd frontend
bun install --frozen-lockfile
bun run build
cd ..
uv build
```

Build Vite zapisuje HTML, JavaScript, CSS i ikony w `portscanner/gui/assets/`.
Ten katalog jest ignorowany przez Git i dołączany do dystrybucji przez Hatchling.
Samo `uv build` na świeżym klonie nie generuje zasobów GUI. `node_modules`
nie jest częścią dystrybucji. Po zmianie frontendu zbuduj go ponownie przed wheel.

## Instalacja przez pipx

Poniższe komendy zakładają wheel wersji `0.1.0`, odpowiadającej metadanym
w `pyproject.toml`. Uruchom je z katalogu repozytorium po zbudowaniu pakietu.
Opcja `--python` wybiera interpreter środowiska projektu odnaleziony przez uv.

CLI i TUI:

```bash
uv tool run --from pipx==1.17.2 pipx install \
  --backend pip --python "$(uv python find)" \
  ./dist/portscanner-0.1.0-py3-none-any.whl
uv tool run --from pipx==1.17.2 pipx ensurepath
```

Dla pełnego desktopu, po buildzie frontendu, zamiast pierwszego polecenia użyj:

```bash
uv tool run --from pipx==1.17.2 pipx install \
  --backend pip --python "$(uv python find)" \
  './dist/portscanner-0.1.0-py3-none-any.whl[gui]'
```

Otwórz nowy terminal po `ensurepath`, a następnie uruchom `portscanner`,
`portscanner --cli` lub, po instalacji dodatku, `portscanner --gui`.
[Tworzenie skrótu macOS](gui.md#skrót-portmanagerapp).

Pipx tworzy osobne środowisko i instaluje zależności z metadanych wheel.
Nie czyta `uv.lock`; instalacja artefaktu jest odrębnym sprawdzeniem od testów repo.
Jeżeli masz już instalację, użyj `pipx install --force` z wybranym wheel,
zachowując `[gui]`, gdy potrzebujesz desktopu. Zachowanie poprzedniego wheel
pozwala zainstalować ponownie wcześniejszą wersję.

Odinstalowanie:

```bash
uv tool run --from pipx==1.17.2 pipx uninstall portscanner
```

## Weryfikacja artefaktu

```bash
uv run --locked python scripts/verify_release.py dist/portscanner-0.1.0-py3-none-any.whl
```

Skrypt instaluje wheel przez pipx w tymczasowym katalogu, sprawdza `pip check`
oraz CLI i TUI headless poza repozytorium. Drukuje nazwę pakietu i SHA256,
po czym usuwa środowisko testowe. Pobiera pipx i zależności, jeżeli nie ma ich
w cache. Nie weryfikuje natywnego GUI ani instalacji dodatku `gui`.

Dodaj `--interactive`, aby sprawdzić zainstalowane TUI w terminalu; `q` kończy
aplikację. Opcja `--python /pełna/ścieżka/do/python` wybiera interpreter.
Kontrole kodu i natywny smoke desktopu: [rozwój i testy](development.md#zakres-testów).

## Platformy i uprawnienia

| Środowisko | Zakres potwierdzonej weryfikacji |
|---|---|
| macOS ARM64 | CLI, TUI, natywne GUI, instalacja wheel i skrót `.app` |
| macOS Intel | Brak potwierdzonej weryfikacji |
| Linux x86_64 / ARM64 | Brak potwierdzonej weryfikacji całej aplikacji |
| Windows | Brak potwierdzonej weryfikacji całej aplikacji |

Na macOS systemowy odczyt gniazd przez psutil może wymagać root. Aplikacja
nie podnosi uprawnień automatycznie. CLI przy błędzie listeners zwraca kod `1`,
nawet gdy JSON zawiera częściowe dane; TUI i GUI pokazują raport źródła.
Odczyt gniazd własnego procesu w teście nie dowodzi widoczności całego systemu.
Na Linuxie niedostępne połączenia mogą zostać pominięte bez błędu.

Modele i obsługa systemów w kodzie nie stanowią deklaracji pełnej zgodności.
[Interpretacja danych i ograniczenia API](core-api.md).
