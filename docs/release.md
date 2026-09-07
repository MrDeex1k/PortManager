# Wydanie MVP 0.1.0

Stan: 2026-09-08; kontrole wykonane 2026-09-07/08. Faza 6 zakończona w uzgodnionym zakresie **macOS**.
Użytkownik odroczył Windows i Linux do czasu udostępnienia środowisk.
Nie oznaczamy tych systemów jako sprawdzonych. Self-hosted CI nadal czeka
na przygotowanie maszyn; nie dodano workflow wymagającego nieistniejących runnerów.

Wydanie jest przygotowane lokalnie: sdist, wheel, instrukcja pipx,
skrypt weryfikacji i [historia zmian](../CHANGELOG.md). Nie opublikowano
taga, GitHub Release ani pakietu na PyPI. Do instalacji używamy lokalnego
artefaktu; zdalna gałąź może jeszcze nie zawierać lokalnych commitów.

## Matryca wykonana na macOS

Host: macOS 26.6.2, ARM64. Zależności testów z `uv.lock`.

| Kontrola | Python 3.12.14 | Python 3.13.9 | Python 3.14.0 |
|---|---|---|---|
| Pełny pytest | 231 OK, 1 pominięty | 231 OK, 1 pominięty | 231 OK, 1 pominięty |
| Pyrefly | 0 błędów | 0 błędów | 0 błędów |
| Instalacja wheel przez pipx i `pip check` | OK | OK | Nie wykonywano |
| CLI + TUI headless z venv pipx | OK | OK | Nie wykonywano |
| Domyślny TUI z pipx w terminalu PTY | Nie wykonywano | OK | Nie wykonywano |

Ruff lint i format: bez błędów. Zbudowano sdist, a następnie wheel z tego
sdist. Testy obejmują rzeczywiste gniazda własnego procesu, odczyt lokalnych IP,
HTTP loopback metryk oraz zakończenie wyłącznie tymczasowego procesu testowego.
TUI Pilot sprawdza filtr, sort, timer, eksport, zgodę/anulowanie, force
i zachowanie celu podczas odświeżania. Dane Docker/tuneli są sprawdzane
głównie przez kontrolowane scenariusze, nie stanowią pełnej matrycy wdrożeń usług.

Pominięty test to systemowy `psutil.net_connections()` wymagający na macOS
dodatkowych uprawnień. CLI bez nich zwraca poprawny JSON, kod 1 i raport
`listeners: error`; TUI pozostaje czynny i pokazuje ograniczenia źródeł.
Odczyt własnych gniazd w teście nie dowodzi pełnej widoczności procesów systemowych.
Nie podnosimy uprawnień automatycznie. W fazie 6 nie odpytano ipify.

## Odtworzenie kontroli

W katalogu repozytorium, po zainstalowaniu uv:

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyrefly check
uv run --locked pytest -q -rs
uv build
uv run --locked python scripts/verify_release.py dist/portscanner-0.1.0-py3-none-any.whl
```

Ostatnia komenda pobiera pipx 1.17.2 i zależności runtime przez pip, instaluje
wheel w tymczasowym katalogu, sprawdza `pip check`, CLI i TUI headless.
Import uruchamia się z `-I` poza repozytorium i musi pochodzić z venv pipx.
Skrypt drukuje wersję Pythona, pakietu oraz SHA256 wheel i usuwa instalację
testową. Nie zmienia globalnej instalacji ani konfiguracji PATH. Cache uv/pip
może zostać wykorzystany; dostęp do indeksu pakietów jest wymagany przy braku cache.

Pipx instaluje zależności z metadanych wheel. Nie czyta `uv.lock`; dlatego
kontrola instalacji jest osobna od testów środowiska deweloperskiego.
Źródła: [instalacja pipx](https://pipx.pypa.io/stable/reference/cli.html),
[izolowane ścieżki pipx](https://pipx.pypa.io/stable/how-to/configure-paths.html).

Rzeczywisty terminal (po starcie sprawdź `/`, `s`, `r`, potem `q`):

```bash
uv run --locked python scripts/verify_release.py dist/portscanner-0.1.0-py3-none-any.whl --interactive
```

Opcja wymaga terminala i po smoke uruchamia zainstalowaną komendę bez flag.
`q` kończy TUI, po czym instalacja testowa zostaje usunięta. Limit czasu
pojedynczego podprocesu skryptu wynosi 5 minut.

Do sprawdzenia innego interpretera dodaj `--python /pełna/ścieżka/do/python`.
Pełne testy innej wersji można uruchomić w osobnym środowisku, zachowując `.venv`:

```bash
UV_PROJECT_ENVIRONMENT=/tmp/portscanner-python312 uv sync --locked --python 3.12
/tmp/portscanner-python312/bin/python -m pytest -q -rs
```

Przed kontrolą finalnego artefaktu zakończ zmiany w kodzie i dokumentacji,
ponownie wykonaj `uv build` i weryfikację wheel. Zmiana plików po zbudowaniu
oznacza, że wcześniejszy artefakt nie jest już wydaniem bieżącego drzewa.

## Instalacja do codziennego użycia na macOS

Zbuduj wheel jak wyżej. Poniższe komendy instalują aplikację trwale przez pipx:

```bash
uv tool run --from pipx==1.17.2 pipx install --backend pip --python "$(uv python find 3.13)" ./dist/portscanner-0.1.0-py3-none-any.whl
uv tool run --from pipx==1.17.2 pipx ensurepath
```

Otwórz nowy terminal, aby wczytać PATH, a następnie:

```bash
portscanner
portscanner --cli --json --no-docker --no-tunnels
```

Jeżeli PortScanner jest już zainstalowany, przed aktualizacją zachowaj wheel
poprzedniej wersji i użyj `pipx install --force` z konkretnym nowym artefaktem.
Powrót do poprzedniej wersji polega na analogicznej instalacji jej wheel.
Odinstalowanie: `uv tool run --from pipx==1.17.2 pipx uninstall portscanner`.
Instrukcje obsługi: [CLI](cli.md), [TUI](tui.md).

## Oczekujące środowiska

| Środowisko | Status |
|---|---|
| macOS ARM64 | Wykonano kontrole powyżej |
| macOS Intel | Nie weryfikowano na tym hoście |
| Linux x86_64 / ARM64 | Odroczone do udostępnienia środowiska |
| Windows | Odroczone do udostępnienia środowiska |

Po uzyskaniu Windows/Linux powtórz lint, format, Pyrefly, pytest, budowanie
i instalację pipx oraz obsługę TUI w natywnym terminalu. Zapisz wersje OS/Pythona,
wyniki i przyczynę każdego pominięcia. Sprawdź odczyty bez uprawnień administratora,
Docker dostępny/niedostępny i konfigurację cloudflared. Operacje kończenia
sprawdzaj wyłącznie na utworzonym procesie testowym. Dopiero rzeczywiste wyniki
pozwalają oznaczyć odpowiedni wiersz jako zweryfikowany.
