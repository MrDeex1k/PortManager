# API core — kontrakt po Fazie 3

Ten kontrakt jest punktem wyjścia dla CLI (Faza 4) i TUI (Faza 5).
Dokumentacja jest po polsku; nazwy symboli i wiadomości commitów po angielsku.
`core/` nie importuje UI. Import pakietu nie wykonuje odczytów ani żądań.

## Główne wejście

```python
from dataclasses import asdict
from portscanner.core import collect_snapshot

snapshot = collect_snapshot(docker=True, tunnels=True, metrics=True, timeout=3.0)
data = asdict(snapshot)  # dane nadają się do json.dumps; tuple stają się tablicami
```

`Snapshot` jest niemutowalną dataclass i zawiera:

| Pole | Typ | Znaczenie |
|---|---|---|
| `ports` | `tuple[PortEntry, ...]` | Gniazda oraz publikacje Dockera bez widocznego gniazda |
| `local_ips` | `tuple[LocalIP, ...]` | Adresy lokalnych interfejsów |
| `docker` | `tuple[DockerPort, ...]` | Wszystkie odczytane publikacje TCP/UDP |
| `tunnels` | `tuple[TunnelInfo, ...]` | Wykryte procesy connectorów, także bez znanych reguł |
| `reports` | `tuple[SourceReport, ...]` | Wyniki źródeł: listeners, processes, local_ips, docker, tunnels |

`SourceReport(source, status, message)` używa stanów `ok`, `partial`,
`unavailable`, `error`, `disabled`. `ok` z pustymi danymi oznacza udany odczyt
bez wyników. `error` lub `unavailable` z pustymi danymi nie oznacza braku usług.
Ograniczenia widoczności psutil opisane w MVP nadal obowiązują, także gdy OS
pomija niedostępne gniazda bez błędu. Odczyty poszczególnych źródeł nie są atomowe.
Interfejs musi pokazać raporty; nie może zamieniać błędu odczytu na „brak portów”.

Błędy operacyjne źródeł znajdują się w raportach i nie blokują pozostałych danych.
Nieprawidłowy argument `timeout` zgłasza `ValueError`. Limit dotyczy pojedynczej
operacji, nie całej migawki. Wywołania są synchroniczne; TUI wykonuje je przez workera poza wątkiem UI.
Wyłączenie `docker`/`tunnels` pomija dane źródło. `metrics=False` pozostawia
wykrywanie procesów i konfiguracji bez HTTP. Exit IP nie jest częścią migawki
ani jej automatycznego odświeżania — nadal służy do tego jawne `fetch_exit_ip()`.

## Wiersz portu

Dotychczasowe pola `proto`, `bind`, `port`, `pid`, `process` pozostają.
Dodane pola:

- `docker: tuple[DockerPort, ...]` — publikacje kontenerów dopasowane do wiersza.
- `tunnels: tuple[TunnelRoute, ...]` — kandydaci z konfiguracji origin.
- `tags: tuple[ServiceTag, ...]` — tagi heurystyczne i ich podstawa.
- `origin: "socket" | "docker"` — pochodzenie wiersza, domyślnie `socket`.

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

## Docker

`collect_docker(timeout=3.0) -> Collection[DockerPort]`, gdzie
`Collection[T]` zawiera `items: tuple[T, ...]` i `report: SourceReport`.

`DockerPort`: `container_id`, `container_name`, `host_bind`, `host_port`,
`container_port`, `proto`, `compose_project`, `compose_service`.

Odczyt używa `docker ps --no-trunc --format json`, następnie `docker inspect`
w paczkach do 64 kontenerów. Szablon inspect zwraca tylko tożsamość, stan,
strukturalne mapowania i dwie etykiety Compose. Nie parsujemy tekstowych zakresów
kolumny Ports; każde rzeczywiste mapowanie jest osobnym obiektem. EXPOSE bez
publikacji, SCTP i porty sieci host bez jawnego mapowania nie tworzą publikacji.
Zniknięcie kontenera/awaria inspect jest raportowana; dane z wcześniejszych
udanych paczek pozostają. Nie startujemy ani nie zatrzymujemy kontenerów.

Respektujemy wybór kontekstu (`DOCKER_CONTEXT` przed `DOCKER_HOST`), ale
odczytujemy tylko lokalny socket `unix:///...` albo pipe `npipe:////./pipe/...`.
Konteksty TCP/SSH i zdalne pipes są pomijane przed połączeniem z daemonem.
Nie zmieniamy aktywnego kontekstu. Docker Desktop/OrbStack przez lokalny socket
jest obsługiwany, mimo że proces kontenera może działać w VM.

Źródła: [docker ps](https://docs.docker.com/reference/cli/docker/container/ls/),
[docker inspect](https://docs.docker.com/reference/cli/docker/inspect/).

## Cloudflare Tunnel

`collect_tunnels(metrics=True, timeout=1.0) -> Collection[TunnelInfo]`.

`TunnelInfo`: `pid`, `routes`, `config_status`, `metrics_status`, `connections`.
`TunnelRoute`: `pid`, `hostname`, `host`, `port`, `path`.

- `config_status`: `explicit` (plik z `--config`), `inferred` (plik domyślny),
  `remote` (token/token-file), `unavailable` lub `error`.
- `metrics_status`: `ok`, `unavailable`, `error` lub `disabled`.
- `connections`: liczba aktywnych połączeń HA albo `None`, gdy brak odczytu.
  Odczytane zero różni się od braku metryki. Dodatnia liczba nie potwierdza hostname.

Najpierw wykrywamy proces `cloudflared` (również `.exe`), pomijając komendy
administracyjne. Bez procesu nie szukamy konfiguracji ani nie odpytujemy portów.
Jawne ścieżki względne są rozwiązywane względem katalogu roboczego procesu.
Pliki domyślne: `.cloudflared/config.yml`/`.yaml` bieżącego użytkownika tylko dla
procesu tego użytkownika oraz `/etc/cloudflared` i `/usr/local/etc/cloudflared`.
Są one jedynie wnioskowanym źródłem. Nawet jawny plik może zmienić się po starcie;
reguły nie są dowodem aktywnej konfiguracji. Nie odczytujemy credentials-file,
tokenów z plików ani zdalnego panelu. Tryb tokenowy ma nieznane lokalnie reguły;
quick tunnel może mieć origin z `--url` i nieznany hostname.

Obsługujemy portowe origin HTTP, HTTPS, SSH, TCP, RDP i SMB. Pomijamy wbudowane
odpowiedzi i Unix sockets, ponieważ nie mają portu TCP. YAML odczytujemy przez
`safe_load` z limitem 1 MiB; błędna konfiguracja nie usuwa informacji o procesie.
Na Linuxie nie przypisujemy localhost ani ścieżek konfiguracji connectorów
z innej lub niedostępnej przestrzeni sieciowej/montowania do hosta — raportujemy
niepełną widoczność. Pełna obsługa connectorów wewnątrz kontenerów jest poza MVP.

Metryki pobieramy z maksymalnie ośmiu gniazd LISTEN przypisanych wykrytemu PID,
wyłącznie na loopback (wildcard jest zamieniany na loopback tej samej rodziny).
Nie zgadujemy właściciela stałego portu 20241. Obsługiwane są zatem także porty
20242–20245 i niestandardowe. Gniazda związane wyłącznie z adresem LAN są pomijane.
HTTP nie korzysta z proxy, DNS ani przekierowań; odpowiedź ma limit 1 MiB.
Parsujemy `cloudflared_tunnel_ha_connections`. Brak dostępu do gniazd PID oznacza
brak metryk, a nie zero połączeń. Nie wykonujemy zapytań do publicznych hostname.

Źródła: [konfiguracja ingress](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/),
[metryki cloudflared](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/monitor-tunnels/metrics/).

## Kubernetes — warstwa 1

`ServiceTag(name, evidence)` ma nazwę `k8s`, `k3s` lub `microk8s` oraz
`evidence="process"` albo `"port"`. Rozpoznajemy dokładną nazwę pliku wykonywalnego,
nie przypadkowe wystąpienie słowa w argumentach. Typowe porty są słabszą
heurystyką, z uwzględnieniem TCP/UDP. Nawet tag oparty na procesie nie dowodzi
przynależności do klastra (np. etcd może działać samodzielnie).
Nie uruchamiamy kubectl, nie odczytujemy kubeconfig i nie kontaktujemy się z klastrem.

## Walidacja Fazy 3

Na macOS/Python 3.13: testy jednostkowe Dockera, tuneli, tagów i scalania;
rzeczywisty HTTP loopback sprawdza odczyt metryk i odrzucanie przekierowań.
Lokalny odczyt Docker zakończył się sukcesem, ale bez opublikowanych mapowań;
nie wykryto działających procesów tuneli. Mapowania, Compose i konfiguracje
zweryfikowano na kontrolowanych danych. Nie uruchamiano kontenerów ani tuneli.
Systemowy odczyt gniazd psutil pozostaje pominięty z powodu uprawnień macOS;
pełna matryca Windows/Linux/macOS pozostaje w Fazie 6.


## Rozszerzenia Fazy 4 — filtry i działania

`core/filtering.py` udostępnia `filter_entries(entries, query) -> list[PortEntry]`.
`None` zachowuje wszystkie wpisy, `:PORT`/`pid:PID` filtrują dokładnie, pozostały
tekst dopasowuje podciąg bez wielkości liter. Błędny filtr zgłasza `ValueError`.

`core/actions.py` jest oddzielony od odczytów. `prepare_kill(pid) -> KillTarget`
sprawdza politykę bez wysyłania sygnału. UI pokazuje dane i musi uzyskać zgodę,
po czym wywołuje `terminate_target(target, force=False, timeout=3.0)`.
Ta funkcja ponownie sprawdza tożsamość i reguły przed sygnałem oraz eskalacją.
Błędy i odmowy zgłaszają `ProcessActionError`; nieprawidłowy timeout `ValueError`.
Wywołania `collect_snapshot()` nigdy nie kończą procesów.
Politykę i allowlistę opisuje [CLI](cli.md); TUI współdzieli te funkcje i zapewnia własny dialog zgody.
