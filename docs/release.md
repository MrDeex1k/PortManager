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
- GUI na macOS wymaga WebKit z obsługą Safari 16.4 lub nowszego (target Vite
  i CSS Tailwind). Sam wpis macOS 12.0 w skrócie `.app` nie gwarantuje tej wersji
  WebKit; na Monterey trzeba również zaktualizować Safari.
  [Dostępność Safari 16.4](https://developer.apple.com/documentation/safari-release-notes/safari-16_4-release-notes).

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

Zalecana ścieżka wydania tworzy sdist i wheel w `dist/`, budując w katalogu
tymczasowym. Wariant CLI/TUI nie dołącza lokalnych zasobów GUI, nawet jeśli
wcześniej zbudowano je w repozytorium:

```bash
uv run --locked python scripts/build_release.py
```

Pełny pakiet z GUI wymaga Bun i Node. Skrypt instaluje zależności frontendu
z lockfile'a w katalogu tymczasowym i zawsze wykonuje świeży build Vite:

```bash
uv run --locked python scripts/build_release.py --gui
```

Opcja `--output /ścieżka` wybiera katalog artefaktów. Skrypt sprawdza tożsamość
pakietu, punkty wejścia oraz kompletność zasobów wskazanych przez HTML przed
opublikowaniem artefaktów. Nieudana kopia nie uszkadza wcześniejszego pliku.
Warianty CLI/TUI i GUI mają tę samą nazwę i wersję wheel; aby zachować oba,
wybierz różne katalogi wyjściowe.

Niskopoziomowe `uv build` nadal działa i tworzy wheel z sdist. Nie uruchamia
Vite: dołącza istniejące `portscanner/gui/assets/`, jeśli są dostępne, bez
sprawdzania ich świeżości. Do wydań używaj skryptu powyżej. Sdist ma jawną listę
katalogów i plików źródłowych; pliki robocze z katalogu głównego, `node_modules`
i raporty testów przeglądarkowych nie są dołączane. Źródłowa ikona 1024 px
pozostaje w sdist, ale nie trafia do zasobów GUI w wheel.

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
oraz CLI i TUI headless poza repozytorium. Kod wyjścia CLI jest porównywany
ze strukturalnym raportem listeners, także przy poprawnym częściowym odczycie.
Drukuje nazwę pakietu i SHA256,
po czym usuwa środowisko testowe. Pobiera pipx i zależności, jeżeli nie ma ich
w cache. Nie dziedziczy docelowych katalogów instalacji pip/pipx ani pliku
konfiguracji pip użytkownika; zachowuje jawne zmienne indeksów i certyfikatów.
Cache pobranych pakietów może zostać uzupełniony.

Pełna paczka GUI wymaga dodatkowej weryfikacji:

```bash
uv run --locked python scripts/verify_release.py dist/portscanner-0.1.0-py3-none-any.whl --gui
```

`--gui` odrzuca wheel bez frontendu, instaluje dodatek `[gui]`, importuje pywebview
i sprawdza metadane oraz ścieżkę zasobów z zainstalowanego pakietu. Nie otwiera
okna i nie potwierdza dostępności natywnego backendu graficznego.
`--inspect-only` sprawdza samo archiwum, bez instalacji i pobierania zależności;
można połączyć tę opcję z `--gui`.

Dodaj `--interactive`, aby sprawdzić zainstalowane TUI w terminalu; `q` kończy
aplikację. Sesja interaktywna nie jest przerywana po pięciu minutach.
Opcja `--python /pełna/ścieżka/do/python` wybiera interpreter.
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
