# TUI — interaktywna tabela portów

Stan Fazy 5 (2026-09-07). Uruchomienie:

```bash
uv run portscanner
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
| `r` | Odśwież teraz, jeśli poprzedni odczyt się zakończył |
| `j` | Zapisz widoczne dane jako JSON |
| `k` | Zweryfikuj proces i otwórz dialog zgody |
| `q` | Wyjdź z aplikacji |

Filtr działa podczas pisania: `:8080` to dokładny port, `pid:42` to dokładny
PID, pozostały tekst wyszukuje także nazwy kontenerów, Compose, hostname tuneli
i tagi. Wielkość liter nie ma znaczenia. Puste pole przywraca wszystkie wpisy.
Błędny filtr pokazuje komunikat przy polu i pustą tabelę; eksport jest wtedy
zablokowany. Litery skrótów w polu filtra są zwykłym tekstem.

Tabela ma kolumny `PROTO`, `BIND`, `PORT`, `PID`, `PROC`, `DOCKER`, `TUNNEL`,
`TAG`, `ŹRÓDŁO`. Bind zawiera adres, port ma własną kolumnę. Przy braku PID
widoczne jest `?`; częściowy odczyt procesu ma status przy nazwie.
Mapowania zawierają nazwę kontenera, host → port kontenera i projekt/usługę
Compose. Tunel jest regułą konfiguracji, a tag K8s heurystyką z podaną podstawą.
`docker` jako źródło oznacza publikację bez potwierdzonego gniazda hosta.
UDP oznacza związane gniazdo, bez potwierdzenia handshake.

Nad tabelą są lokalne IP, czas ostatniego odczytu i raporty niedostępnych lub
częściowych źródeł. Długie sekcje i tabela mają przewijanie. Brak uprawnień
nie zamyka aplikacji i nie powoduje automatycznego podniesienia uprawnień.
Nieoczekiwany błąd całego odświeżenia pozostawia poprzednią migawkę z jawnym
komunikatem. Pusta tabela nie jest dowodem braku portów, gdy źródło zawiodło.

## Odświeżanie i struktura

Timer `set_interval(2.0)` zleca odczyt w tle. W danej chwili trwa najwyżej jeden
odczyt; ticki i `r` podczas jego trwania są pomijane. Długa operacja nie blokuje
pisania ani nawigacji. Domyślny timeout core wynosi 3 s dla pojedynczej operacji,
nie całej migawki. Wyjście może poczekać na już rozpoczęty odczyt wątku.

Różnice są nanoszone przez dodanie/usunięcie wierszy i aktualizację zmienionych
komórek, bez czyszczenia całej tabeli. Klucz to `(proto, bind, port, pid, origin)`:
rozszerza pierwotny plan o PID i pochodzenie, aby nie scalać procesów
współdzielących port ani publikacji Dockera. Sortowanie używa liczbowych portów
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
   `terminate` kończy proces twardo. Domyślny timeout oczekiwania to 3 s.
5. Wynik operacji jest widoczny w pasku komunikatów; po sukcesie zlecane jest
   odświeżenie. Błąd nie zamyka TUI. W czasie weryfikacji i kończenia nie można
   zlecić kolejnego kill ani wyjść przez `q`; filtr i nawigacja pozostają aktywne.

## Weryfikacja Fazy 5

Testy [Textual Pilot](https://textual.textualize.io/guide/testing/) obejmują
start, skróty, filtr, sortowanie, różnice migawek i zaznaczenie, tick timera
przy wolnym odczycie, raporty i odzyskanie działania po błędzie, JSON i odmowę
nadpisania, anulowanie/zgodę/force oraz zmianę tabeli podczas dialogu.
Wolne kończenie procesu nie blokuje nawigacji ani nie uruchamia drugiej operacji.
Testy interakcji nie wysyłają sygnałów do rzeczywistych procesów.

macOS / Python 3.13: 231 testów zaliczonych, 1 pominięty z powodu uprawnień
systemowego odczytu gniazd. Ruff lint i format bez błędów, Pyrefly 0 błędów.
Uruchomiono także komendę `portscanner` w terminalu PTY: pokazała raporty
ograniczeń odczytu i zamknęła się przez `q` z kodem 0. Pełna matryca terminali
Windows/Linux/macOS oraz instalacja release przez pipx pozostają w Fazie 6.
Zbudowano sdist i wheel; wheel zawiera cały pakiet `tui/` oraz wspólne
formatowanie `presentation.py`.

Aktualna weryfikacja wydania na macOS, pipx i odroczone środowiska
Windows/Linux: [Faza 6](release.md).
