# CLI — Faza 4

## Uruchamianie

```bash
uv run portscanner --cli
uv run portscanner --cli --json
uv run portscanner --cli --filter :8080
uv run portscanner --cli --filter pid:4123
uv run portscanner --cli --filter postgres
uv run portscanner --cli --no-docker --no-tunnels --no-color
```

`portscanner --help` nie wykonuje odczytów systemowych. Brak `--cli` wybiera
interaktywny [TUI](tui.md), dostępny od Fazy 5.
Opcje odczytu/kończenia wymagają `--cli`. CLI jest jednorazowe, bez `--watch`.

Tabela pokazuje protokół, bind, port, PID, proces, mapowania Dockera, reguły
tunelu, tagi i pochodzenie danych. Lokalne adresy interfejsów są pod tabelą.
Stan `access_denied` lub `gone` pozostaje widoczny; nieznany PID to `?`.
Wiersz `origin=docker` nie potwierdza gniazda hosta, a `[config]` przy tunelu
nie potwierdza dostępności hostname. Tagi są heurystyką. Tekst procesów i
konfiguracji nie jest interpretowany jako Rich markup ani sterowanie terminalem.

## Flagi odczytu

| Flaga | Znaczenie |
|---|---|
| `--cli` | Jednorazowy odczyt wspólnej migawki |
| `--json` | Wyłącznie tablica `PortEntry` na stdout |
| `--filter QUERY` | Filtr po odczycie; składnia poniżej |
| `--no-color` | Wyłączenie kolorów tabeli; przy przekierowaniu terminal jest wykrywany automatycznie |
| `--no-docker` | Bez uruchamiania Docker CLI |
| `--no-tunnels` | Bez wykrywania konfiguracji i metryk tuneli |
| `--no-metrics` | Bez HTTP loopback metryk; procesy i config tuneli nadal odczytywane |
| `--timeout SECONDS` | Dodatni, skończony timeout operacji, domyślnie 3 s |
| `--exit-ip` | Jawne HTTPS do ipify, wyłącznie w trybie tabeli |

Exit IP nie jest odczytywany domyślnie. `--exit-ip` ujawnia ipify adres
wyjściowy trasy i drukuje etykietę „exit IP (widziane z internetu)”. Flaga nie
łączy się z `--json` ani `--kill`. Timeout ma znaczenie opisane w API core:
dotyczy operacji, nie całego skanowania ani twardego limitu DNS.

## Filtry

- `:8080` — dokładny numer portu 1–65535, także publikacja hosta Docker.
- `pid:4123` — dokładny PID; nieznany PID nie pasuje.
- Pozostały tekst — podciąg bez rozróżniania wielkości liter w protokole,
  bindzie, porcie, PID, nazwie/argumentach procesu, kontenerze, projekcie/usłudze
  Compose, hostname tunelu, tagu lub pochodzeniu danych.
- `::1` jest tekstowym filtrem IPv6, nie składnią numeru portu.
- Puste filtry i błędne zakresy są odrzucane przed odczytem systemu.

Brak dopasowań to poprawna pusta lista, o ile podstawowy odczyt się udał.
Filtr nie ogranicza danych zbieranych ze źródeł i nie steruje `--kill`.

## JSON i kody wyjścia

`--json` zachowuje kontrakt `list[PortEntry]` z [API core](core-api.md).
Na stdout nie trafiają tabela, nagłówki, IP, potwierdzenia ani raporty źródeł.
Znaki specjalne są kodowane przez JSON, także przy wymuszonych kolorach terminala.
Przykładowy kontrakt obejmujący zagnieżdżone dane jest utrwalony w
`tests/fixtures/cli_ports.json` i sprawdzany przez `typer.testing.CliRunner`.

Raporty `partial`, `unavailable` i `error` trafiają na stderr. Błąd opcjonalnego
Dockera/tuneli/procesów/IP nie usuwa portów i nie zmienia samodzielnie kodu 0,
jeśli źródło listeners zostało odczytane poprawnie. Nadal trzeba czytać stderr.
Błąd listeners daje kod 1, nawet gdy stdout zawiera częściowe dane z Dockera.
Nie należy uznawać pustej tablicy za brak portów bez sprawdzenia kodu wyjścia.

| Kod | Znaczenie |
|---|---|
| `0` | Odczyt podstawowy udany (także brak dopasowań), pomoc lub zakończenie procesu |
| `1` | Brak odczytu listeners, błąd jawnego exit IP, odmowa/anulowanie/błąd operacji kill |
| `2` | Nieprawidłowe argumenty lub niedozwolone połączenie flag |

Na macOS systemowy odczyt psutil może wymagać root; CLI nie podnosi uprawnień.
Ograniczenia widoczności systemu pozostają opisane w API core.

## Kończenie procesu

```bash
uv run portscanner --cli --kill 4123
uv run portscanner --cli --kill 4123 --force --timeout 3
```

CLI odczytuje i pokazuje nazwę oraz argumenty, następnie pyta o potwierdzenie
(domyślnie „nie”). Brak odpowiedzi/EOF lub odmowa nie wysyłają sygnału.
Nie ma flagi pomijającej potwierdzenie. `--kill` nie łączy się z filtrami,
JSON, exit IP ani opcjami wyboru źródeł. Nie wykonuje pełnej migawki ani HTTP.

Znane flagi uwierzytelniające są maskowane jako `***` zarówno w JSON,
jak i w argumentach pokazywanych przed zgodą. Pełne argumenty służą jedynie
do wewnętrznego porównania tożsamości celu. Zakres i ograniczenia maskowania:
[API core](core-api.md#prywatność-argumentów-procesów).

Wspólny moduł `core/actions.py` wprowadza następującą politykę MVP:

1. Tylko własny proces użytkownika, z widocznym gniazdem TCP LISTEN lub związanym
   UDP bez peera. Na POSIX zgodne muszą być realny i efektywny UID; na Windows
   konto procesu. Na Linuxie wymagane są te same przestrzenie sieci i montowania.
2. PID 0/1, skaner i jego procesy nadrzędne są chronione. Procesy infrastruktury
   (m.in. docker-proxy, dockerd, containerd, kubelet, kube-apiserver, etcd, k3s)
   są blokowane. Dla docker-proxy komunikat wskazuje `docker stop <nazwa>`;
   aplikacja nie wykonuje tej komendy sama.
3. Nazwa procesu **i** pliku wykonywalnego muszą pasować do allowlisty:
   `node`, `nodejs`, `bun`, `deno`, `php`, `ruby`, `java`, `dotnet`, `uvicorn`,
   `gunicorn`, `flask`, `rails`, `python`, `python3`, `python3.N` lub
   `kubectl port-forward`. Uwzględniane są ścieżki i sufiks `.exe`.
   Przed `port-forward` obsługiwane są `-n`, `--namespace`, `--context`,
   `--kubeconfig` oraz długie formy z `=`. Inne polecenia kubectl są blokowane.
   Procesy spoza listy (także własny niestandardowy binarny serwer) są odrzucane;
   rozszerzenie listy wymaga świadomej zmiany polityki w kodzie.
4. Po potwierdzeniu ponownie sprawdzane są właściciel, reguły, gniazdo oraz PID,
   czas utworzenia, nazwa, executable i argumenty. Zmiana danych wymaga nowej zgody.
5. Wysyłany jest `terminate()` i następuje oczekiwanie. Bez `--force` timeout
   kończy się błędem; sygnał terminate został już wysłany. Z `--force` po timeout
   tożsamość i reguły są ponownie sprawdzane, potem następuje `kill()` i oczekiwanie.
   Przy eskalacji nie wymagamy nadal otwartego gniazda, bo proces mógł je już zamknąć.

Na Windows `terminate()` również kończy proces twardo. Operacje nie są
transakcją; zakończonego procesu nie przywracamy. Błąd weryfikacji/uprawnień
powoduje odmowę działania, bez automatycznego sudo/UAC. TUI od Fazy 5 wykorzystuje
te same funkcje `prepare_kill` i `terminate_target` oraz własny dialog zgody.

## Weryfikacja Fazy 4

macOS/Python 3.13: 214 testów zaliczonych, 1 pominięty z powodu systemowych
uprawnień psutil; Ruff lint + format bez błędów, Pyrefly 0 błędów.
Testy obejmują JSON golden, stdout/stderr, filtry, błędne argumenty, politykę
kill, zmianę PID/danych, odmowę zgody i eskalację. Rzeczywiście zakończono tylko
tymczasowy serwer loopback utworzony przez test. Zainstalowany entry point CLI
sprawdzono także na realnej odmowie odczytu macOS: poprawny JSON, stderr i kod 1.
Żadne testy CLI nie odpytują publicznego ipify. Matryca OS pozostaje w Fazie 6.
