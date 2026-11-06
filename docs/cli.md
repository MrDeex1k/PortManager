# CLI — polecenia i automatyzacja

## Uruchamianie

```bash
uv run --locked portscanner --cli
uv run --locked portscanner --cli --json
uv run --locked portscanner --cli --json-snapshot
uv run --locked portscanner --cli --columns PROTO,BIND,PORT,PID,PROC
uv run --locked portscanner --cli --filter :8080
uv run --locked portscanner --cli --filter pid:4123
uv run --locked portscanner --cli --filter postgres
uv run --locked portscanner --cli --no-docker --no-tunnels --no-color
```

`portscanner --help` nie wykonuje odczytów systemowych. Brak `--cli` wybiera
interaktywny [TUI](tui.md).
Opcje odczytu/kończenia wymagają `--cli`, poza `--kube`, które działa też w TUI/GUI. CLI jest jednorazowe, bez `--watch`.

Tabela pokazuje protokół, bind, port, PID, proces, mapowania Dockera, reguły
tunelu, tagi, mapowania Kubernetes i pochodzenie danych. Lokalne adresy interfejsów są pod tabelą.
Stan `access_denied` lub `gone` pozostaje widoczny; nieznany PID to `?`.
Wiersz `origin=docker` nie potwierdza gniazda hosta, a `[config]` przy tunelu
nie potwierdza dostępności hostname. Tagi są heurystyką. Tekst procesów i
konfiguracji nie jest interpretowany jako Rich markup ani sterowanie terminalem.
`--columns` wybiera kolejność i zestaw kolumn, co ułatwia odczyt w wąskim terminalu.
Nazwy są rozdzielane przecinkami, bez rozróżniania wielkości liter; powtórzenia
i nieznane nazwy są błędem. Opcja działa wyłącznie z tabelą.
Dostępne nazwy: `PROTO`, `BIND`, `PORT`, `PID`, `PROC`, `DOCKER`, `TUNNEL`,
`TAG`, `KUBERNETES`, `ŹRÓDŁO`.
Pod tabelą są wszystkie wykryte connectory Cloudflare Tunnel, niezależnie od
filtra portów: PID, stan konfiguracji i metryk, liczba połączeń (`?`, gdy nieznana)
oraz kody przyczyn błędów. Connector bez lokalnych tras również pozostaje widoczny.

## Flagi odczytu

| Flaga | Znaczenie |
|---|---|
| `--cli` | Jednorazowy odczyt wspólnej migawki |
| `--kube` | Opcjonalny odczyt Kubernetes; [kontrakt i ograniczenia](kubernetes.md) |
| `--json` | Wyłącznie tablica `PortEntry` na stdout |
| `--json-snapshot` | Obiekt pełnej migawki: porty, IP, Docker, connectory i raporty |
| `--columns LIST` | Wybrane kolumny tabeli, np. `PROTO,BIND,PORT,PID,PROC` |
| `--filter QUERY` | Filtr po odczycie; składnia poniżej |
| `--no-color` | Wyłączenie kolorów tabeli; przy przekierowaniu terminal jest wykrywany automatycznie |
| `--no-docker` | Bez uruchamiania Docker CLI |
| `--no-tunnels` | Bez wykrywania konfiguracji i metryk tuneli |
| `--no-metrics` | Bez HTTP loopback metryk; procesy i config tuneli nadal odczytywane |
| `--timeout SECONDS` | Budżet I/O każdego źródła Docker/Tunnel/Kubernetes lub czas oczekiwania na zakończenie procesu; >0 i ≤3600 s, domyślnie 3 s |
| `--exit-ip` | Jawne HTTPS do ipify, wyłącznie w trybie tabeli |

Exit IP nie jest odczytywany domyślnie. `--exit-ip` ujawnia ipify adres
wyjściowy trasy i drukuje etykietę „exit IP (widziane z internetu)”. Flaga nie
łączy się z trybami JSON ani `--kill`. Każde opcjonalne źródło ma osobny budżet
`--timeout`: wszystkie jego polecenia lub odczyty konfiguracji i metryk dzielą
pozostały czas. Limit nie obejmuje całego skanowania, odczytów psutil ani parsowania.
Dla `--kill` jest to czas oczekiwania osobno po terminate i po kill.
Dla exit IP dotyczy operacji gniazda, bez twardego limitu DNS.
[Szczegóły budżetów i sprzątania](core-api.md#główne-wejście).
Jawne `--timeout 3` również wymaga `--cli`; wartość domyślna nie omija kontroli trybu.

## Filtry

- `:8080` — dokładny numer portu 1–65535, także publikacja hosta Docker.
- `pid:4123` — dokładny PID; nieznany PID nie pasuje.
- Pozostały tekst — podciąg bez rozróżniania wielkości liter w protokole,
  bindzie, porcie, PID, nazwie/argumentach procesu, kontenerze, projekcie/usłudze
  Compose, hostname tunelu, tagu, namespace/zasobie/węźle/kontekście Kubernetes
  lub pochodzeniu danych.
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
Lista jest zapisywana strumieniowo po jednym rekordzie, bez budowania dodatkowej
kopii całej listy i całego tekstu JSON w pamięci.

Osobna opcja `--json-snapshot` zapisuje obiekt z polami `ports`, `local_ips`,
`docker`, `tunnels` i `reports`. Filtr ogranicza wyłącznie `ports`; pozostałe pola
opisują pełny odczyt źródeł, w tym connectory bez powiązanych portów i kody błędów.
Nie można łączyć obu formatów JSON. Raporty ostrzegawcze nadal trafiają na stderr.

Raporty `partial`, `unavailable` i `error`, wraz z kodami przyczyn, trafiają na stderr. Błąd opcjonalnego
Dockera/tuneli/procesów/IP/Kubernetes nie usuwa portów i nie zmienia samodzielnie kodu 0,
jeśli źródło listeners zostało odczytane poprawnie. Nadal trzeba czytać stderr.
Błąd listeners daje kod 1, nawet gdy stdout zawiera częściowe dane z Dockera.
Nie należy uznawać pustej tablicy za brak portów bez sprawdzenia kodu wyjścia.
Wyjątkiem jest `listeners: partial [udp_peer_unknown]`: odczyt gniazd się udał,
ale Windows nie udostępnia informacji o peerze UDP. Ten przypadek zwraca kod 0
z ostrzeżeniem. Inny częściowy odczyt, np. fallback na macOS, nadal daje kod 1.

| Kod | Znaczenie |
|---|---|
| `0` | Odczyt podstawowy udany (także brak dopasowań), pomoc lub zakończenie procesu |
| `1` | Nieudany lub niepełny odczyt listeners (poza `udp_peer_unknown`), błąd jawnego exit IP, odmowa/anulowanie/błąd operacji kill |
| `2` | Nieprawidłowe argumenty lub niedozwolone połączenie flag |

Na macOS systemowy odczyt psutil może wymagać root; CLI nie podnosi uprawnień.
Ograniczenia widoczności systemu pozostają opisane w API core.

## Kończenie procesu

```bash
uv run --locked portscanner --cli --kill 4123
uv run --locked portscanner --cli --kill 4123 --force --timeout 3
```

CLI odczytuje i pokazuje nazwę oraz argumenty, następnie pyta o potwierdzenie
(domyślnie „nie”). Brak odpowiedzi/EOF lub odmowa nie wysyłają sygnału.
Nie ma flagi pomijającej potwierdzenie. `--kill` nie łączy się z filtrami,
JSON, exit IP ani opcjami wyboru źródeł. Nie wykonuje pełnej migawki ani HTTP.

Znane flagi uwierzytelniające są maskowane jako `***` zarówno w JSON,
jak i w argumentach pokazywanych przed zgodą. Pełne argumenty służą jedynie
do wewnętrznego porównania tożsamości celu. Zakres i ograniczenia maskowania:
[API core](core-api.md#prywatność-argumentów-procesów).

Wspólny moduł `core/actions.py` wprowadza następujące reguły:

1. Tylko własny proces użytkownika, z widocznym gniazdem TCP LISTEN lub związanym
   UDP bez widocznego peera (na Windows stan peera jest nieznany). Na POSIX zgodne muszą być realny i efektywny UID; na Windows
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
   otwiera drugie pytanie o zgodę na kill tego samego procesu (domyślnie „nie”).
   Kontynuacja jest możliwa także po zamknięciu portu i wygasa po 120 sekundach.
   Odmowa kończy polecenie kodem 1; terminate został już wysłany.
   Z `--force` po timeout
   tożsamość i reguły są ponownie sprawdzane, potem następuje `kill()` i oczekiwanie.
   Przy eskalacji nie wymagamy nadal otwartego gniazda, bo proces mógł je już zamknąć.

Na Windows `terminate()` również kończy proces twardo. Operacje nie są
transakcją; zakończonego procesu nie przywracamy. Błąd weryfikacji/uprawnień
powoduje odmowę działania, bez automatycznego sudo/UAC. TUI wykorzystuje
te same funkcje `prepare_kill` i `terminate_target` oraz własny dialog zgody.


Platformy i instalacja: [instalacja i pakowanie](release.md).
