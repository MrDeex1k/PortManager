# API core — wspólny kontrakt CLI/TUI/GUI

Pakiet `portscanner.core` udostępnia wspólny model i odczyty dla trzech interfejsów.
`core/` nie importuje UI. Import pakietu nie wykonuje odczytów ani żądań.

## Główne wejście

```python
from dataclasses import asdict
from portscanner.core import collect_snapshot

snapshot = collect_snapshot(
    docker=True, tunnels=True, metrics=True, kube=False, timeout=3.0
)
data = asdict(snapshot)  # json.dumps(data) serializuje tuple jako tablice JSON
```

`Snapshot` jest niemutowalną dataclass i zawiera:

| Pole | Typ | Znaczenie |
|---|---|---|
| `ports` | `tuple[PortEntry, ...]` | Gniazda, publikacje Dockera i opcjonalne konfiguracje NodePort |
| `local_ips` | `tuple[LocalIP, ...]` | Adresy lokalnych interfejsów |
| `docker` | `tuple[DockerPort, ...]` | Wszystkie odczytane publikacje TCP/UDP |
| `tunnels` | `tuple[TunnelInfo, ...]` | Wykryte procesy connectorów, także bez znanych reguł |
| `reports` | `tuple[SourceReport, ...]` | Wyniki źródeł: listeners, processes, local_ips, docker, tunnels i opcjonalnie kubernetes |

`SourceReport(source, status, message)` używa stanów `ok`, `partial`,
`unavailable`, `error`, `disabled`. `ok` z pustymi danymi oznacza udany odczyt
bez wyników. `error` lub `unavailable` z pustymi danymi nie oznacza braku usług.
Na macOS systemowy odczyt psutil może wymagać root. Po odmowie migawka próbuje
odczytać gniazda dostępnych procesów i oznacza wynik jako `partial`.
`accessible_fallback=False` wyłącza tę próbę; odmowa ma status `unavailable`.
Błędy natywne psutil, w tym `RuntimeError`, są izolowane do danego źródła. Na Linuxie niedostępne
gniazda mogą zostać pominięte bez błędu. Wynik nie gwarantuje pełnej widoczności
systemu, a odczyty poszczególnych źródeł nie są atomowe.
Interfejs musi pokazać raporty; nie może zamieniać błędu odczytu na „brak portów”.

Błędy operacyjne źródeł znajdują się w raportach i nie blokują pozostałych danych.
Nieprawidłowy argument `timeout` zgłasza `ValueError`. Docker, Tunnel i Kubernetes
mają osobne wspólne budżety I/O dla danego kolektora, nie dla całej migawki.
Odczyty metadanych systemowych i parsowanie nie są przerywane; do czasu operacji
może dojść ograniczone oczekiwanie na sprzątnięcie podprocesu.
Wywołania są synchroniczne; TUI wykonuje je przez workera poza wątkiem UI.
`SourceReport.code` zawiera bezpieczną przyczynę błędu, np. `timeout`,
`output_limit`, `command_failed`, `invalid_data`, `not_found` lub `remote_endpoint`.
Pole jest `None`, gdy nie ma kodu diagnostycznego; surowy stderr nie jest eksportowany.
`listeners: partial` z kodem `udp_peer_unknown` oznacza pełny odczyt gniazd
z niedostępną informacją o peerze UDP na Windows. CLI zachowuje wtedy kod 0
i ostrzeżenie. Kod ten nie zastępuje błędu ani częściowego odczytu gniazd.

Interfejsy cyklicznie odświeżające dane przekazują opcjonalne
`kube_discovery=KubeDiscovery()` z `portscanner.core.kube_cache` do
`collect_snapshot(kube=True, kube_discovery=...)`. Instancja należy do sesji
interfejsu: odczytuje NodePort w tle, przechowuje wynik przez 30 s i zawsze
rozpoznaje port-forward z bieżących lokalnych danych. Raport zawiera `last_success_at` (ISO 8601 UTC), `age_seconds` (wiek liczony
zegarem monotonicznym), `stale` i `refreshing`; bez udanego odczytu czas i wiek
są `None`. Wiek jest również opisany w wiadomości raportu Kubernetes. `request_refresh()` omija TTL, `reset()`
unieważnia dane i wynik odczytu w toku, a `close()` kończy sesję i czeka na
sprzątnięcie ograniczonego czasowo odczytu. Bez `kube=True` instancja nie jest
wywoływana. Bez instancji odczyt Kubernetes pozostaje synchroniczny.
Zmiana ścieżek lub metadanych plików kubeconfig usuwa również ostatni udany
wynik. Ręczne odświeżenie podczas odczytu zostaje zapamiętane na kolejny skan.

Nieparsowalny adres IP pomija tylko pojedynczy rekord gniazda lub interfejsu;
pozostałe dane nadal są przetwarzane. Błędy odczytu systemowego pozostają
odpowiednio `ListenerScanError` / `LocalIPError` i trafiają do raportów źródeł.
Wyłączenie `docker`/`tunnels` pomija dane źródło. `metrics=False` pozostawia
wykrywanie procesów i konfiguracji bez HTTP. Exit IP nie jest częścią migawki
ani jej automatycznego odświeżania — nadal służy do tego jawne `fetch_exit_ip()`.

## Wiersz portu

`PortEntry` zawiera protokół `proto`, adres `bind`, numer `port`, opcjonalny
`pid` i szczegóły `process: ProcessInfo | None` oraz powiązania:

- `docker: tuple[DockerPort, ...]` — publikacje kontenerów dopasowane do wiersza.
- `tunnels: tuple[TunnelRoute, ...]` — kandydaci z konfiguracji origin.
- `kubernetes: tuple[KubernetesPort, ...]` — konfiguracja NodePort lub cel port-forward.
- `tags: tuple[ServiceTag, ...]` — tagi heurystyczne i ich podstawa.
- `udp_peer_status: "not_applicable" | "absent" | "unknown"` — widoczność peera
  lokalnego gniazda UDP; `not_applicable` dotyczy TCP i wpisów konfiguracyjnych.
- `origin: "socket" | "docker" | "kubernetes"` — pochodzenie wiersza, domyślnie `socket`.

`origin="docker"` oznacza publikację zgłoszoną przez Docker bez odpowiadającego
wpisu psutil. Nie potwierdza TCP LISTEN ani dostępności usługi; `pid` i `process`
pozostają `None`. Jeden wiersz może mieć kilka mapowań lub reguł tunelu.
Kolejność wierszy: port, protokół, bind, PID, pochodzenie.

Dopasowanie Dockera wymaga identycznego bindu, protokołu i portu hosta;
`bind="*"` dopasowuje oba wildcardy `0.0.0.0`/`::`. Rozbieżne bindy pozostają
osobno. Dopasowanie nie dowodzi własności PID przez kontener. Nie kopiujemy PID
z przestrzeni kontenera do hosta. Reguły tunelu dopasowujemy tylko do TCP,
zgodnego portu i lokalnego adresu; `localhost` oznacza loopback/wildcard.
Nie rozwiązujemy nazw origin przez DNS. Reguły zachowują kolejność i `path`;
przypisanie reguły do portu nie ocenia priorytetów routingu ani osiągalności hostname.
Relacje tuneli są dołączane po utworzeniu wszystkich wierszy, także NodePort.
Scalanie indeksuje kandydatów według protokołu/portu, zachowując kolejność reguł.
Strefa IPv6 z URL (`%25en0`) jest normalizowana do postaci systemowej (`%en0`),
bez usuwania identyfikatora interfejsu.

## Szczegóły procesu

`enrich_processes()` z `core/procs.py` uzupełnia wpisy o `ProcessInfo`:
`pid`, `name`, `cmdline` (tuple argumentów lub `None`) i status odczytu.
Status to `ok`, `unknown` (brak PID), `access_denied`, `gone` lub `error`.
Brak szczegółów nie usuwa wpisu portu. Odmowa odczytu argumentów może zachować
nazwę procesu. PID jest odczytywany raz na migawkę, bez cache między skanami.
Informacyjna migawka procesu nie upoważnia do operacji bez ponownej weryfikacji.

## Prywatność argumentów procesów

`read_process()` maskuje wartości znanych flag przed utworzeniem `ProcessInfo`.
Dotyczy to `--token`, `--token-file`, `--access-token`, `--auth-token`,
`--password`, `--passwd`, `--api-key`, `--secret` i `--client-secret`, w postaci
`--flaga wartość` oraz `--flaga=wartość`. Nazwy są rozpoznawane bez wielkości
liter, także z `_` zamiast `-`. Wartość jest zastępowana przez `***`, a granice
argumentów i pozostałe argumenty są zachowane. Jeśli oczekiwana wartość sama
jest znaną flagą sekretu, maskowanie obejmuje także jej wartość:
`["--password", "--token", "sekret"]` daje `["--password", "***", "***"]`.

Migawki, filtr po argumentach i eksport JSON używają zamaskowanych danych.
Dialogi kończenia procesu w CLI/TUI korzystają z tego samego maskowania,
ale wewnętrzny `KillTarget` zachowuje pełne argumenty do ponownej weryfikacji.
Zmiana sekretu po potwierdzeniu oznacza zmianę tożsamości i wymaga nowej zgody.
Maskowanie nie rozpoznaje wszystkich sposobów przekazywania sekretów: dowolne
argumenty pozycyjne, niestandardowe flagi i sekrety w URL mogą pozostać widoczne.

## Docker

`collect_docker(timeout=3.0) -> Collection[DockerPort]`, gdzie
`Collection[T]` zawiera `items: tuple[T, ...]` i `report: SourceReport`.

`DockerPort`: `container_id`, `container_name`, `host_bind`, `host_port`,
`container_port`, `proto`, `compose_project`, `compose_service`.

Odczyt używa `docker ps --quiet --no-trunc`, następnie `docker inspect`
w paczkach do 64 kontenerów. Szablon inspect zwraca tylko tożsamość, stan,
strukturalne mapowania i dwie etykiety Compose. Nie parsujemy tekstowych zakresów
kolumny Ports; każde rzeczywiste mapowanie jest osobnym obiektem. EXPOSE bez
publikacji, SCTP i porty sieci host bez jawnego mapowania nie tworzą publikacji.
Puste `HostPort` w trybie routed nie tworzy publikacji hosta. Numery portów
muszą być ciągami cyfr ASCII; wartości bool/float nie są konwertowane.
Po niezerowym kodzie inspect zachowujemy poprawne rekordy stdout i kontynuujemy
kolejne paczki. Błędny rekord lub binding nie usuwa zdrowych sąsiadów; raport
otrzymuje stan częściowy, jeśli pozostały mapowania. Publiczny `parse_inspect`
pozostaje ścisły i odrzuca nieprawidłowe dane.
Kontekst, ps i wszystkie paczki dzielą jeden budżet czasu. Każde polecenie ma
limit 4 MiB stdout + stderr egzekwowany podczas odczytu. Nie startujemy ani
nie zatrzymujemy kontenerów.

Respektujemy wybór kontekstu (`DOCKER_CONTEXT` przed `DOCKER_HOST`), ale
odczytujemy tylko lokalny socket `unix:///...` albo pipe `npipe:////./pipe/...`.
Konteksty TCP/SSH i zdalne pipes są pomijane przed połączeniem z daemonem.
Nie zmieniamy aktywnego kontekstu. Docker Desktop/OrbStack przez lokalny socket
jest obsługiwany, mimo że proces kontenera może działać w VM.

Źródła: [docker ps](https://docs.docker.com/reference/cli/docker/container/ls/),
[docker inspect](https://docs.docker.com/reference/cli/docker/inspect/).

## Cloudflare Tunnel

`collect_tunnels(metrics=True, timeout=1.0) -> Collection[TunnelInfo]`.

`TunnelInfo`: `pid`, `routes`, `config_status`, `metrics_status`, `connections`,
`config_code`, `metrics_code` (opcjonalne przyczyny problemów).
`TunnelRoute`: `pid`, `hostname`, `host`, `port`, `path`.

- `config_status`: `explicit` (plik z `--config`), `inferred` (plik domyślny),
  `remote` (token/token-file), `unavailable` lub `error`.
- `metrics_status`: `ok`, `unavailable`, `error` lub `disabled`.
- `connections`: liczba aktywnych połączeń HA albo `None`, gdy brak odczytu.
  Odczytane zero różni się od braku metryki. Dodatnia liczba nie potwierdza hostname.

Najpierw wykrywamy proces `cloudflared` (również `.exe`), pomijając komendy
administracyjne. Bez procesu nie szukamy konfiguracji ani nie odpytujemy portów.
Parser oddziela wartości znanych opcji od podkomend; nieznane opcje pomija
konserwatywnie wraz z nierozpoznanym procesem. Nazwa pliku `info` nie jest komendą.
Nierozpoznane opcje oznaczają częściową widoczność w raporcie; rozpoznane komendy
administracyjne są pomijane bez takiego ostrzeżenia.
Jawne ścieżki względne są rozwiązywane względem katalogu roboczego procesu.
Pliki domyślne: `.cloudflared/config.yml`/`.yaml` bieżącego użytkownika tylko dla
procesu tego użytkownika oraz `/etc/cloudflared` i `/usr/local/etc/cloudflared`.
Są one jedynie wnioskowanym źródłem. Nawet jawny plik może zmienić się po starcie;
reguły nie są dowodem aktywnej konfiguracji. Nie odczytujemy credentials-file,
zawartości token-file ani zdalnego panelu. Tryb tokenowy rozpoznajemy po opcjach,
obecności `TUNNEL_TOKEN`/`TUNNEL_TOKEN_FILE` w środowisku procesu oraz kluczach
`token`/`token-file` już odczytanego YAML. Wartości sekretów nie są zachowywane
w modelu ani logowane. Niedostępne środowisko daje `environment_unavailable`
i nie przypisuje lokalnych tras o niepewnym pochodzeniu.
Tryb tokenowy ma nieznane lokalnie reguły; quick tunnel może mieć origin
z `--url` (także bez schematu, domyślnie HTTP) i nieznany hostname.

Obsługujemy portowe origin HTTP, HTTPS, SSH, TCP, RDP i SMB. Pomijamy wbudowane
odpowiedzi (`hello_world`, `hello-world`, `http_status`), `socks-proxy`, bastion
i Unix sockets, ponieważ nie wskazują stałego portu TCP. `bastionMode` uwzględnia
ustawienia globalne i nadpisanie przez regułę.
Odczyt YAML z limitem 1 MiB odbywa się w osobnym, ograniczonym czasowo procesie;
FIFO i urządzenia są odrzucane po sprawdzeniu deskryptora, również przez symlink.
Parsowanie używa `safe_load`. Błędna konfiguracja nie usuwa informacji o procesie.
Na Linuxie nie przypisujemy localhost ani ścieżek konfiguracji connectorów
z innej lub niedostępnej przestrzeni sieciowej/montowania do hosta — raportujemy
niepełną widoczność. Connectory wewnątrz kontenerów nie mają gwarantowanej pełnej widoczności.

Metryki pobieramy z maksymalnie ośmiu gniazd LISTEN przypisanych wykrytemu PID,
wyłącznie na loopback (wildcard jest zamieniany na loopback tej samej rodziny).
Nie zgadujemy właściciela stałego portu 20241. Obsługiwane są zatem także porty
20242–20245 i niestandardowe. Gniazda związane wyłącznie z adresem LAN są pomijane.
HTTP nie korzysta z proxy, DNS ani przekierowań; odpowiedź ma limit 1 MiB.
Konfiguracje i metryki wszystkich PID dzielą budżet `timeout`, odmierzany zegarem
monotonicznym. Każda kolejna próba otrzymuje pozostały czas; po jego wyczerpaniu
connectory pozostają widoczne z kodem `timeout`, lecz nie zaczynamy nowego I/O.
Odczyt HTTP ma dodatkowo termin przerwania gniazda obejmujący nagłówki i treść;
powolny strumień małych porcji nie przedłuża żądania.
Inne kody connectora to m.in. `unsafe_file`, `output_limit`, `unsupported_origin`,
`invalid_data`, `http_status`, `metrics_unavailable` i `namespace_unavailable`.
Parsujemy `cloudflared_tunnel_ha_connections`. Brak dostępu do gniazd PID oznacza
brak metryk, a nie zero połączeń. Nie wykonujemy zapytań do publicznych hostname.

Źródła: [konfiguracja ingress](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/),
[metryki cloudflared](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/monitor-tunnels/metrics/).

## Heurystyczne tagi Kubernetes

`ServiceTag(name, evidence)` ma nazwę `k8s`, `k3s` lub `microk8s` oraz
`evidence="process"` albo `"port"`. Rozpoznajemy dokładną nazwę pliku wykonywalnego,
nie przypadkowe wystąpienie słowa w argumentach. Typowe porty są słabszą
heurystyką, z uwzględnieniem TCP/UDP. Nawet tag oparty na procesie nie dowodzi
przynależności do klastra (np. etcd może działać samodzielnie).
Samo tagowanie nie uruchamia kubectl, nie odczytuje kubeconfig i nie kontaktuje się z klastrem.

Jawne `collect_snapshot(kube=True)` włącza odczyt klastra i raport `kubernetes`.
Szczegóły modeli, lokalności, odczytu klastra i timeoutu: [Kubernetes](kubernetes.md).

## Filtry i działania

`core/filtering.py` udostępnia `filter_entries(entries, query) -> list[PortEntry]`.
`None` zachowuje wszystkie wpisy, `:PORT`/`pid:PID` filtrują dokładnie, pozostały
tekst dopasowuje podciąg bez wielkości liter przez Unicode `casefold()`
(np. `STRASSE` pasuje do `Straße`). Podgląd Vue używa generowanej tabeli
`frontend/src/casefold.ts` i tych samych przypadków testowych co Python.
Błędny filtr zgłasza `ValueError`.

`core/actions.py` jest oddzielony od odczytów. `prepare_kill(pid) -> KillTarget`
sprawdza politykę bez wysyłania sygnału. UI pokazuje dane i musi uzyskać zgodę,
po czym wywołuje `terminate_target(target, force=False, timeout=3.0)`.
Ta funkcja ponownie sprawdza tożsamość i reguły przed sygnałem oraz eskalacją.
Wynik to `terminated` albo `already_exited` (proces zniknął podczas oczekiwania
po terminate lub zweryfikowano jego zakończenie podczas eskalacji).
Timeout po wysłaniu terminate bez force zgłasza `TerminationPending`, podklasę
`ProcessActionError`. Jej `pending.resume(timeout=...)` wolno wywołać dopiero po
nowej zgodzie na kill. Kontynuacja jest jednorazowa i ważna 120 sekund; zachowuje
kontrolę właściciela, przestrzeni nazw i tożsamości, ale nie wymaga otwartego portu.
Nowa operacja przez `prepare_kill` nadal wymaga gniazda.

Błędy i odmowy zgłaszają `ProcessActionError`; nieprawidłowy timeout `ValueError`.
Wywołania `collect_snapshot()` nigdy nie kończą procesów.
Politykę i allowlistę opisuje [CLI](cli.md); TUI współdzieli te funkcje i zapewnia własny dialog zgody.

## Gniazda i adresy IP

`collect_listeners()` z `core/listeners.py` zwraca lokalne TCP LISTEN oraz
związane gniazda UDP bez zdalnego adresu. Nie wysyła pakietów; wpis UDP nie
potwierdza odpowiedzi serwera. Na Windows psutil nie udostępnia zdalnego adresu
UDP: `udp_peer_status="unknown"` i raport `partial` opisują to ograniczenie.
Nieznany właściciel oznaczony przez Windows jako PID 0 jest normalizowany do `None`.
Wysokie porty nie są odrzucane. Para wildcard
IPv4/IPv6 tego samego znanego PID, protokołu i portu może być prezentowana
jako `bind="*"`; `group_dual_stack=False` zachowuje osobne adresy.
Błędy odczytu zgłaszają `ListenerScanError`, a odmowa dostępu
`ListenerAccessDenied`, jego podklasę. Nieznany właściciel ma `pid=None`.

`collect_local_ips()` z `core/ips.py` zwraca `list[LocalIP]`, w tym loopback,
VPN i link-local. Zachowuje scope IPv6 z systemu. Nie wybiera adresu głównego,
nie wykonuje żądań sieciowych; błędy zgłasza jako `LocalIPError`.

`fetch_exit_ip(timeout=3.0)` jest osobnym, jawnym żądaniem HTTPS do
`api64.ipify.org`. Zwraca `ExitIP` z etykietą „exit IP (widziane z internetu)”
lub zgłasza `ExitIPError`. Wynik opisuje trasę użytego połączenia, także VPN
lub proxy, i ujawnia usłudze jej adres wyjściowy. Nie potwierdza dostępności
portów z internetu ani adresu routera. Funkcja nie ponawia żądań, ogranicza
odpowiedź do 64 bajtów i waliduje publiczny adres IP. Timeout dotyczy operacji
gniazda, nie całego wywołania ani twardego limitu DNS.
