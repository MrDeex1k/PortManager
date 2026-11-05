# Kubernetes — NodePort i port-forward

`--kube` włącza odczyt konfiguracji klastra
przez zainstalowany `kubectl` oraz rozpoznawanie lokalnych sesji port-forward.
Bez tej flagi aplikacja nie uruchamia kubectl ani nie czyta kubeconfig;
heurystyczne tagi K8s nadal działają.

```bash
uv run --locked portscanner --cli --kube
uv run --locked portscanner --cli --kube --json --filter demo
uv run --locked portscanner --kube                       # TUI
uv run --locked --extra gui portscanner --gui --kube     # GUI
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
Udany pusty odczyt usuwa stare mapowania. Zmiana lokalnych IP, przełącznika lub
rewizji kubeconfig unieważnia cache, ostatni sukces i wynik wcześniejszego żądania.
Rewizja obejmuje ścieżki, urządzenie/inode, rozmiar oraz czasy modyfikacji i zmiany
każdego pliku `KUBECONFIG` (domyślnie `~/.kube/config`), bez odczytu sekretów.
Ręczne „Odśwież” / `r` omija cache; żądanie podczas aktywnego odczytu zostaje
zapamiętane na kolejny skan. Odczyty nie nakładają się. CLI i domyślne API core nadal
wykonują jednorazowy odczyt synchroniczny.

## Odczyt klastra

Kubectl wybiera bieżący kontekst ze standardowego kubeconfig (w tym
zmiennej `KUBECONFIG`). Korzysta z jego uwierzytelnienia; konfiguracja może
uruchamiać pluginy exec. Aplikacja nie wyświetla kubeconfig, tokenów ani
surowego stderr. Nie zmienia kontekstu, usług ani innych zasobów klastra.
`--kube` zezwala na kontakt z API wybranego klastra, także zdalnego.
Nie są wykonywane próby połączeń z portami usług.

Najpierw `kubectl config current-context` ustala kontekst. Jedno `kubectl
--context NAME get services,nodes --all-namespaces` pobiera oba rodzaje zasobów
z jawnym kontekstem, zapisanym też w mapowaniach NodePort. Kontrola rewizji przed
i po odczycie odrzuca wynik, jeśli konfiguracja zmieniła się w trakcie.
Szablon Go przekazuje tylko nazwy, namespace, typ i porty usług oraz adresy węzłów;
pomija m.in. obrazy, adnotacje i managedFields. Redukcja dotyczy wyjścia kubectl,
nie rozmiaru odpowiedzi API pobieranej przez samo kubectl.
Oba polecenia dzielą budżet 3 s, z `--request-timeout` i timeoutem procesu.
Kubectl ma zamknięte stdin.
Łączny limit stdout i stderr (4 MiB) jest egzekwowany podczas odbierania.
Po każdym odczycie kończymy grupę procesów na macOS/Linux oraz zaobserwowanych
potomków, także po utworzeniu przez nich nowej sesji. Nadzór POSIX jest best effort:
proces, który odłączy się i zostanie osierocony między próbkami, może pozostać
niewykryty. Nie jest to izolacja systemowa. Taki potomek nie blokuje zamknięcia
wątków czytających stdout/stderr. Oczekiwanie na proces po sygnale jest ograniczone.
Windows używa Job Object
z `KILL_ON_JOB_CLOSE`. Proces pomocniczy czeka na przypisanie do joba przed
uruchomieniem kubectl, więc potomkowie należą do joba także po zakończeniu
rodzica. Nieudane przypisanie przerywa start kubectl. Konto potrzebuje uprawnień listowania services we wszystkich
namespace oraz nodes. Te odczyty nie stanowią atomowej migawki klastra.

Brak kubectl daje `unavailable`, a błąd konfiguracji, RBAC, timeout lub
nieprawidłowe dane — `error`. Jeśli pozostały rozpoznane lokalne sesje
port-forward, raport ma stan `partial`. Błąd Kubernetes nie usuwa pozostałych
źródeł i nie zmienia kodu CLI, jeśli odczyt listeners się powiódł.
`SourceReport.code` rozróżnia m.in. `timeout`, `output_limit`, `command_failed`,
`invalid_data`, `not_found` i `config_changed`, bez ujawniania stderr.

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

`collect_snapshot(kube=True)` dodaje raport `kubernetes`. `PortEntry` zawiera
pole `kubernetes: tuple[KubernetesPort, ...]` (JSON: tablica, domyślnie
pusta), także przy wyłączonej fladze. Każde mapowanie zawiera:

- `kind`: `nodeport` lub `port-forward`;
- `namespace`: nazwa lub `null`, gdy nieznana;
- `resource`: np. `service/web` lub zasób z argumentów;
- `remote_port`: tekstowy port usługi / cel port-forward;
- `context`: kontekst odczytu NodePort albo jawny kontekst z argumentów
  port-forward; `null`, jeśli nieznany;
- `node`: nazwa węzła dla NodePort lub `null`.

Wiersze NodePort grupujemy po protokole, adresie i porcie, zachowując wszystkie
mapowania. Filtr tekstowy uwzględnia namespace, zasób, węzeł, kontekst i rodzaj
mapowania. Konsumenci JSON powinni uwzględniać pole `kubernetes` oraz
`origin="kubernetes"` w walidacji schematu.


## Zakres zgodności

Zweryfikowana platforma aplikacji to macOS ARM64. Integracja z klastrem
w VM nie oznacza, że adres węzła jest lokalnym adresem hosta: NodePort może
nie utworzyć wpisu, mimo że API klastra odpowiada poprawnie. Sam odczyt API
nie potwierdza pełnej widoczności gniazd hosta.
[Platformy i uprawnienia](release.md#platformy-i-uprawnienia).

Źródła kontraktu Kubernetes:
[Service i NodePort](https://kubernetes.io/docs/concepts/services-networking/service/),
[kubectl port-forward](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/).
