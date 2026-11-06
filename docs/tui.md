# TUI — interaktywna tabela portów

Uruchomienie z katalogu repozytorium po instalacji zależności:

```bash
uv run --locked portscanner
```

Brak flag uruchamia Textual. Jednorazowy odczyt nadal wymaga `--cli`;
flagi odczytu i operacji opisane w [CLI](cli.md) należą do tego trybu.
TUI używa domyślnych źródeł `collect_snapshot()`: lokalnych gniazd, procesów,
IP, Dockera oraz konfiguracji i metryk loopback cloudflared. Nie odpytuje ipify.

## Obsługa

| Klawisz | Działanie |
|---|---|
| `/` | Przenieś fokus do filtra |
| `Enter` / `Esc` w filtrze | Wróć do tabeli, zachowując filtr |
| `Ctrl+Shift+A`, potem `Backspace` | Wyczyść filtr i pokaż wszystkie wpisy |
| Strzałki góra/dół | Zaznacz wiersz |
| Strzałki lewo/prawo | Przewijaj szeroką tabelę |
| `s` | Przełącz sortowanie rosnące: port / nazwa procesu |
| `r` | Odśwież teraz lub zapamiętaj żądanie do wykonania po bieżącym odczycie |
| `j` | Zapisz widoczne dane jako JSON |
| `d` | Otwórz pełną diagnostykę migawki; `Esc` zamyka |
| `k` | Zweryfikuj proces i otwórz dialog zgody |
| `q` | Wyjdź z aplikacji |
| `Ctrl+Q` | Wyjdź również z pola filtra, z zachowaniem blokady trwających operacji |
| `Tab` / `Shift+Tab` | Przejdź między filtrem, panelami informacji i tabelą |

Filtr działa podczas pisania: `:8080` to dokładny port, `pid:42` to dokładny
PID, pozostały tekst wyszukuje także nazwy kontenerów, Compose, hostname tuneli
i tagi oraz pola Kubernetes. Wielkość liter nie ma znaczenia. Puste pole przywraca wszystkie wpisy.
Błędny filtr pokazuje komunikat przy polu i pustą tabelę; eksport jest wtedy
zablokowany. Litery skrótów w polu filtra są zwykłym tekstem.

Tabela ma kolumny `PROTO`, `BIND`, `PORT`, `PID`, `PROC`, `DOCKER`, `TUNNEL`,
`TAG`, `KUBERNETES`, `ŹRÓDŁO`. Bind zawiera adres, port ma własną kolumnę. Przy braku PID
widoczne jest `?`; częściowy odczyt procesu ma status przy nazwie.
Mapowania zawierają nazwę kontenera, host → port kontenera i projekt/usługę
Compose. Tunel jest regułą konfiguracji, a tag K8s heurystyką z podaną podstawą.
`docker` jako źródło oznacza publikację bez potwierdzonego gniazda hosta.
UDP oznacza związane gniazdo, bez potwierdzenia handshake. Na Windows peer UDP
jest nieznany, więc lista może zawierać także endpointy klientów; raport
`listeners: partial [udp_peer_unknown]` opisuje to ograniczenie.

Nad tabelą są lokalne IP, czas ostatniego odczytu i raporty niedostępnych lub
częściowych źródeł. Długie sekcje i tabela mają przewijanie. Brak uprawnień
nie zamyka aplikacji i nie powoduje automatycznego podniesienia uprawnień.
Nieoczekiwany błąd całego odświeżenia pozostawia poprzednią migawkę z jawnym
komunikatem. Pusta tabela nie jest dowodem braku portów, gdy źródło zawiodło.
Panele IP, raportów, connectorów i komunikatów można przewijać z klawiatury:
po ustawieniu fokusu użyj strzałek, PageUp/PageDown lub Home/End.
`Esc` wraca do tabeli. Widok `d` pokazuje pełne raporty wraz z kodami przyczyn,
lokalne IP oraz wszystkie connectory, również bez dopasowanych portów.
Connectory są również w osobnym panelu głównym: PID, stan konfiguracji i metryk,
liczba połączeń oraz kody błędów. Filtr portów nie ukrywa connectorów.

## Odświeżanie i struktura

Timer `set_interval(2.0)` zleca odczyt w tle. W danej chwili trwa najwyżej jeden
odczyt; ticki podczas jego trwania są pomijane. Ręczne `r` oraz odświeżenie po
zakończeniu procesu zapisują jedno oczekujące żądanie. Wynik wcześniejszego skanu
jest wtedy pomijany, a worker wykonuje kolejny odczyt bez nakładania operacji.
Wymuszenie Kubernetes jest przekazywane także podczas aktywnego skanu.
Długa operacja nie blokuje pisania ani nawigacji. Docker, Tunnel i Kubernetes
mają osobne budżety I/O po 3 s; polecenia i odczyty danego kolektora dzielą
jego budżet. Nie jest to limit całej migawki ani odczytów psutil i parsowania;
sprzątanie podprocesów może dodatkowo wydłużyć oczekiwanie.
Wyjście może poczekać na już rozpoczęty odczyt wątku.

Różnice są nanoszone przez dodanie/usunięcie wierszy i aktualizację zmienionych
komórek, bez czyszczenia całej tabeli. Niezmienione wpisy nie są ponownie formatowane.
Klucz to `(proto, bind, port, pid, origin)`:
rozróżnia procesy współdzielące port oraz publikacje Dockera. Sortowanie używa liczbowych portów
i PID. Zaznaczony wpis pozostaje zaznaczony po sortowaniu i odświeżeniu, o ile
nadal jest widoczny; po jego usunięciu kursor zostaje przy najbliższym wierszu.

`portscanner/tui/app.py` zarządza widokiem i workerami, `tui/dialogs.py` dialogiem.
`presentation.py` współdzieli komórki z CLI i neutralizuje znaki sterujące oraz
markup. `core/` pozostaje niezależny od interfejsów. Worker korzysta
z `asyncio.to_thread`, a aktualizacje widoku wykonuje na wątku UI.
Wzorce API: [workery Textual](https://textual.textualize.io/guide/workers/),
[DataTable](https://textual.textualize.io/widgets/data_table/).

## Eksport JSON

`j` zapisuje nowy plik `portscanner-YYYYMMDD-HHMMSS-mikrosekundy.json` w katalogu,
z którego uruchomiono aplikację. Pasek komunikatów pokazuje ścieżkę lub błąd.
Zapis obejmuje migawkę **widocznych wpisów w kolejności tabeli z chwili naciśnięcia
klawisza**, ze wszystkimi polami modelu, także argumentami procesu. Format to
ta sama tablica `PortEntry`, co `--cli --json`; nie zawiera raportów źródeł
ani lokalnych IP. Przy niedostępnym źródle wynik może być częściowy — stan
źródeł pozostaje widoczny w TUI.
Eksport jest zapisywany strumieniowo po jednym rekordzie, w wątku roboczym.

Argumenty w eksporcie i dialogu kończenia mają zamaskowane wartości znanych
flag uwierzytelniających. Pozostałe argumenty są zachowane; zakres maskowania
opisuje [API core](core-api.md#prywatność-argumentów-procesów).

Plik jest tworzony wyłącznie jako nowy; kolizja nazwy lub istniejący symlink
powodują błąd bez nadpisywania. Na POSIX plik ma uprawnienia `0600` (na Windows
obowiązują ACL katalogu). Nieudany zapis usuwa rozpoczęty plik. Eksporty o tym
wzorcu nazw są ignorowane przez Git. W czasie zapisu drugi eksport jest
pomijany, a `q` prosi o poczekanie na wynik.

## Kończenie procesu

`k` działa dla zaznaczonego gniazda ze znanym PID. Publikacje Docker kierują
do zarządzania kontenerem przez `docker stop <nazwa>`; aplikacja sama nie
wykonuje tej komendy. Politykę i pełną allowlistę opisuje [CLI](cli.md).

1. Worker wywołuje `prepare_kill(pid)`: sprawdza właściciela, allowlistę,
   chronione procesy, gniazdo i tożsamość. Odmowa trafia do paska komunikatów.
2. Dialog pokazuje PID, nazwę, plik wykonywalny i argumenty. Domyślny przycisk
   to **Anuluj**; `Esc` również anuluje. Kończenie dotyczy całego procesu,
   a więc wszystkich jego portów.
3. **Zakończ proces** wywołuje `terminate_target()` z dokładnym `KillTarget`
   pokazanym w dialogu. Odświeżenia i zmiany zaznaczenia nie zmieniają celu.
   Core ponownie weryfikuje tożsamość i politykę przed sygnałem.
4. Checkbox `--force` jest domyślnie wyłączony. Zaznaczenie zezwala na `kill`
   dopiero po timeout `terminate` i kolejnej weryfikacji. Na Windows także
   `terminate` kończy proces twardo; dialog to opisuje i ukrywa checkbox.
   Domyślny timeout oczekiwania to 3 s. Bez force po timeoutcie pojawia się
   nowy dialog zgody na kill, ważny 120 sekund, także po zamknięciu portu.
5. Wynik operacji jest widoczny w pasku komunikatów; po sukcesie zlecane jest
   odświeżenie. Błąd nie zamyka TUI. W czasie weryfikacji i kończenia nie można
   zlecić kolejnego kill ani wyjść przez `q`; filtr i nawigacja pozostają aktywne.

## Opcjonalny Kubernetes

`portscanner --kube` włącza kontekst Kubernetes. Lokalne cele port-forward są
aktualizowane przy każdym skanie, a dane NodePort są odczytywane w tle co 30 s.
`r` wymusza odświeżenie danych klastra. Wiek danych i ewentualny błąd odczytu
są widoczne w podsumowaniu; po błędzie zachowywane są poprzednie mapowania.
Kolumna KUBERNETES pokazuje namespace, zasób, port docelowy i pochodzenie
mapowania. Błędy źródła pozostają w raportach; filtr i eksport uwzględniają
nowe dane. [Zakres i ograniczenia](kubernetes.md).

Platformy i instalacja: [instalacja i pakowanie](release.md).
