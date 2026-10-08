# Kubernetes — opcjonalna warstwa 2

Stan implementacji: 2026-10-08. `--kube` włącza odczyt konfiguracji klastra
przez zainstalowany `kubectl` oraz rozpoznawanie lokalnych sesji port-forward.
Bez tej flagi aplikacja nie uruchamia kubectl ani nie czyta kubeconfig;
heurystyczne tagi K8s z warstwy 1 nadal działają.

```bash
uv run portscanner --cli --kube
uv run portscanner --cli --kube --json --filter demo
uv run portscanner --kube                       # TUI
uv run --extra gui portscanner --gui --kube     # GUI
```

CLI pozwala zmienić budżet źródła przez `--timeout`; TUI i GUI używają 3 s.
Flaga `--kube` nie łączy się z `--kill`. W GUI filtr Kubernetes pokazuje
mapowania, a inspektor ich namespace, zasób, port docelowy oraz węzeł/kontekst.
Eksport JSON wszystkich interfejsów zachowuje te same pola.

GUI ma przełącznik „Włącz Kubernetes” w widoku Kubernetes, dostępny także
po uruchomieniu `PortManager.app` z Findera. Bez `--kube` odczyt jest domyślnie
wyłączony; ustawienie obowiązuje w bieżącej sesji aplikacji.

GUI i TUI odczytują klaster w osobnym wątku co 30 s (licząc od zakończenia
poprzedniej próby). Lokalne porty i cele port-forward nadal są aktualizowane
przy każdym skanie co 2 s; wolny klaster nie opóźnia lokalnej migawki.
Pierwszy skan pokazuje „Odczyt klastra w toku”. Wiek danych klastra jest
widoczny w widoku Kubernetes GUI i podsumowaniu TUI. Błąd odświeżenia
zachowuje ostatnie dane NodePort ze stanem `partial` i podanym wiekiem.
Udany pusty odczyt usuwa stare mapowania. Zmiana lokalnych IP lub przełącznika
unieważnia cache i wynik wcześniejszego żądania. Ręczne „Odśwież” / `r` omija
cache; żądania klastra nie nakładają się. CLI i domyślne API core nadal
wykonują jednorazowy odczyt synchroniczny.

## Odczyt klastra

Kubectl wybiera bieżący kontekst ze standardowego kubeconfig (w tym
zmiennej `KUBECONFIG`). Korzysta z jego uwierzytelnienia; konfiguracja może
uruchamiać pluginy exec. Aplikacja nie wyświetla kubeconfig, tokenów ani
surowego stderr. Nie zmienia kontekstu, usług ani innych zasobów klastra.
`--kube` zezwala na kontakt z API wybranego klastra, także zdalnego.
Nie są wykonywane próby połączeń z portami usług.

Jedno polecenie `kubectl get services,nodes --all-namespaces --output=json`
ustala kontekst raz dla obu rodzajów zasobów. Budżet polecenia wynosi 3 s,
z `--request-timeout` i timeoutem procesu. Kubectl ma zamknięte stdin.
Łączny limit stdout i stderr (4 MiB) jest egzekwowany podczas odbierania.
Po timeout lub przekroczeniu limitu proces i jego potomkowie są kończone;
na macOS/Linux używamy osobnej grupy procesów. Windows używa Job Object
z `KILL_ON_JOB_CLOSE`. Proces pomocniczy czeka na przypisanie do joba przed
uruchomieniem kubectl, więc potomkowie należą do joba także po zakończeniu
rodzica. Nieudane przypisanie przerywa start kubectl. Natywne testy Windows
są dostępne w `tests/test_windows_job.py`; Windows pozostaje poza matrycą
zweryfikowaną na macOS. Konto potrzebuje uprawnień listowania services we wszystkich
namespace oraz nodes. Te odczyty nie stanowią atomowej migawki klastra.

Brak kubectl daje `unavailable`, a błąd konfiguracji, RBAC, timeout lub
nieprawidłowe dane — `error`. Jeśli pozostały rozpoznane lokalne sesje
port-forward, raport ma stan `partial`. Błąd Kubernetes nie usuwa pozostałych
źródeł i nie zmienia kodu CLI, jeśli odczyt listeners się powiódł.

## NodePort

Obsługiwane są przydzielone `nodePort` w usługach NodePort i LoadBalancer,
dla TCP i UDP. Numer pochodzi z API; nie zakładamy domyślnego zakresu
30000–32767. ClusterIP, SCTP i nieprzydzielone porty są pomijane.

Adres InternalIP/ExternalIP węzła musi odpowiadać adresowi lokalnego
interfejsu. Loopback i adresy wildcard są pomijane. Bez dopasowania IP nie
powstaje lokalny wiersz. Dotyczy to również klastrów działających w VM,
których adresy nie należą do hosta.

Dopasowanie adresu jest wskazówką, nie dowodem tożsamości węzła: prywatne
adresy mogą powtarzać się między sieciami. Rekord ma `origin="kubernetes"`,
`pid=null`, `process=null` i jawnie opisuje konfigurację. Nie przypisujemy go
do procesu hosta nawet przy zgodności numeru portu. Konfiguracja kube-proxy
(`nodePortAddresses`), firewall i routing mogą uniemożliwiać dostęp. Nie
potwierdzamy aktywnego gniazda ani dostępności usługi. Wiersz nie pozwala
na operację zakończenia procesu.

## Port-forward

Rozpoznawane są gniazda TCP z odczytanym PID i argumentami procesu kubectl.
Obsługujemy zasób (np. `svc/web`, `pod/web`, `deployment/web`), kilka portów,
`LOCAL:REMOTE`, `LOCAL:NAZWA` i pojedynczy port. Numer lokalny musi odpowiadać
zaobserwowanemu gniazdu tego PID. Opcje mogą występować przed lub po komendzie;
namespace przyjmujemy z `-n`, `-nNAME`, `--namespace` lub `--namespace=NAME`.

Namespace i kontekst są zapisywane tylko wtedy, gdy podano je w argumentach.
Nie odtwarzamy historycznego kontekstu działającego procesu z bieżącego pliku.
Nieznane opcje oraz dynamiczny port lokalny (`:REMOTE`) są pomijane bez
zgadywania. Brak dostępu do argumentów lub PID ogranicza wykrywanie.
Cel jest informacją z cmdline, nie potwierdzeniem działania tunelu ani
identyfikacją konkretnego poda wybranego przez usługę.

## Kontrakt

`collect_snapshot(kube=True)` dodaje raport `kubernetes`. `PortEntry` ma
nowe pole `kubernetes: tuple[KubernetesPort, ...]` (JSON: tablica, domyślnie
pusta), także przy wyłączonej fladze. Każde mapowanie zawiera:

- `kind`: `nodeport` lub `port-forward`;
- `namespace`: nazwa lub `null`, gdy nieznana;
- `resource`: np. `service/web` lub zasób z argumentów;
- `remote_port`: tekstowy port usługi / cel port-forward;
- `context`: jawny kontekst z argumentów port-forward lub `null`;
- `node`: nazwa węzła dla NodePort lub `null`.

Wiersze NodePort grupujemy po protokole, adresie i porcie, zachowując wszystkie
mapowania. Filtr tekstowy uwzględnia namespace, zasób, węzeł, kontekst i rodzaj
mapowania. Dodanie pola oraz wartości `origin="kubernetes"` wymaga aktualizacji
konsumentów JSON, którzy walidują zamkniętą listę pól lub wartości origin.

## Weryfikacja

Weryfikacja usprawnień 2026-10-08 na macOS: **349 testów zaliczonych,
4 pominięte** (systemowy odczyt gniazd i 3 natywne testy Windows).
Ruff lint/format i Pyrefly bez błędów; frontend: 4 testy Bun, vue-tsc,
formatowanie i build Vite zaliczone. Natywny smoke WebKit potwierdził
przełącznik Kubernetes, filtr, inspektor, eksport i operacje na procesach.
Testy cache obejmują nieblokujący odczyt, TTL, ręczne odświeżenie, zmianę IP,
wyłączenie w trakcie żądania i zachowanie danych po błędzie klastra.

Weryfikacja 2026-10-03 na macOS: pytest **325 zaliczonych, 1 pominięty**
(uprawnienia systemowego odczytu gniazd), Ruff lint/format i Pyrefly bez błędów.
Frontend: formatowanie, vue-tsc, 3 testy Bun i produkcyjny build Vite zaliczone.
Natywny smoke WebKit zaliczony, w tym filtr i inspektor Kubernetes.

Testy używają kontrolowanych odpowiedzi kubectl: lokalny/zdalny węzeł, IPv6,
TCP/UDP, niestandardowy zakres portów, błędne dane, timeout i brak uprawnień.
Sprawdzają też port-forward, domyślny brak odczytu klastra, serializację mostka
i wybór interfejsu z `--kube`. Natywny smoke GUI obejmuje filtr Kubernetes,
inspektor NodePort i brak przycisku zakończenia procesu dla wpisu konfiguracji.

### Próba na rzeczywistym OrbStack — 2026-10-03

Klaster `orbstack`, Kubernetes `v1.35.6+orb1`, węzeł Ready. Utworzono
izolowany namespace z nginx i usługą NodePort; bez zmian istniejących aplikacji.

- Pod osiągnął Ready. HTTP przez lokalny port-forward zwróciło 200.
- Core rozpoznał rzeczywiste gniazda procesu kubectl (IPv4/IPv6), PID,
  namespace, kontekst oraz nazwany port docelowy `http`.
- Odczyt services/nodes przez `collect_kube` dał raport `ok`.
- NodePort nie został przypisany do macOS, ponieważ IP węzła nie jest lokalnym
  IP hosta. Parser utworzył poprawne rekordy bez PID dla danych z żywego API
  i rzeczywistych interfejsów Linux odczytanych w kontenerze z siecią hosta.
  Nie był to pełny przebieg aplikacji uruchomionej na Linuxie.
- Rzeczywista odmowa RBAC (impersonowany użytkownik bez dostępu) dała
  `partial` i zachowała mapowania port-forward. Nie zmieniano ról klastra.
- Nieosiągalny endpoint w tymczasowej kopii kubeconfig dał `partial` po około
  1 s przy budżecie 1 s. Nie wyłączano API użytkownika.
- Pełne CLI na macOS zachowało poprawny JSON i zgłosiło kod 1: brak uprawnień
  do systemowego odczytu listeners. Kubernetes miał status `ok`. Test
  port-forward korzystał z rzeczywistych gniazd odczytanych bezpośrednio dla
  własnego procesu potomnego; nie dowodzi widoczności w zwykłym pełnym skanie.

Po testach potwierdzono brak testowych namespace i procesów port-forward.
Tymczasowe kopie kubeconfig usunięto; bieżący kontekst pozostał `orbstack`.
Pełna weryfikacja aplikacji na Linuxie i pełnego odczytu gniazd na macOS
z odpowiednimi uprawnieniami pozostają osobnymi kontrolami.

Źródła kontraktu Kubernetes:
[Service i NodePort](https://kubernetes.io/docs/concepts/services-networking/service/),
[kubectl port-forward](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/).

### Poprawki po przeglądzie

Pojedynczy odczyt services/nodes zapobiega mieszaniu kontekstów. Runner
ogranicza na bieżąco stdout i stderr łącznie oraz sprząta procesy potomne.
Regresje korzystają z rzeczywistych procesów testowych, w tym symulowanego
pluginu uwierzytelniającego. Pełna kontrola po poprawkach: **331 testów
zaliczonych, 1 pominięty**, Ruff i Pyrefly bez błędów. Ponowny odczyt
rzeczywistego OrbStack przez nowy runner: `kubernetes: ok`.
