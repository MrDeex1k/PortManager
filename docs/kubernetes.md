# Kubernetes — opcjonalna warstwa 2

Stan implementacji: 2026-10-03. `--kube` włącza odczyt konfiguracji klastra
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

## Odczyt klastra

Kubectl wybiera bieżący kontekst ze standardowego kubeconfig (w tym
zmiennej `KUBECONFIG`). Korzysta z jego uwierzytelnienia; konfiguracja może
uruchamiać pluginy exec. Aplikacja nie wyświetla kubeconfig, tokenów ani
surowego stderr. Nie zmienia kontekstu, usług ani innych zasobów klastra.
`--kube` zezwala na kontakt z API wybranego klastra, także zdalnego.
Nie są wykonywane próby połączeń z portami usług.

Wykonywane są dwa odczyty: `kubectl get services --all-namespaces --output=json`
i `kubectl get nodes --all-namespaces --output=json`, z pozostałym
`--request-timeout` i timeoutem procesu. Wspólny budżet obu poleceń wynosi
3 s. Kubectl ma zamknięte stdin. Odpowiedź większa niż 4 MiB jest odrzucana
po odebraniu. Konto potrzebuje uprawnień listowania services we wszystkich
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

Weryfikacja 2026-10-03 na macOS: pytest **325 zaliczonych, 1 pominięty**
(uprawnienia systemowego odczytu gniazd), Ruff lint/format i Pyrefly bez błędów.
Frontend: formatowanie, vue-tsc, 3 testy Bun i produkcyjny build Vite zaliczone.
Natywny smoke WebKit zaliczony, w tym filtr i inspektor Kubernetes.

Testy używają kontrolowanych odpowiedzi kubectl: lokalny/zdalny węzeł, IPv6,
TCP/UDP, niestandardowy zakres portów, błędne dane, timeout i brak uprawnień.
Sprawdzają też port-forward, domyślny brak odczytu klastra, serializację mostka
i wybór interfejsu z `--kube`. Natywny smoke GUI obejmuje filtr Kubernetes,
inspektor NodePort i brak przycisku zakończenia procesu dla wpisu konfiguracji.

Test z rzeczywistym klastrem i jego RBAC pozostaje do wykonania; nie
uruchamiano ani nie modyfikowano klastra użytkownika.

Źródła kontraktu Kubernetes:
[Service i NodePort](https://kubernetes.io/docs/concepts/services-networking/service/),
[kubectl port-forward](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/).
