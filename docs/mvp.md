# PortScanner - MVP

> Scope MVP: tylko to urządzenie (localhost). Bez skanowania zdalnych hostów.
> Funkcje: Local + Global IP, lista portów LISTEN, proces na porcie, mapowania Docker
> (`run` / `compose`), wykrywanie Cloudflare Tunnel lokalnie.

---

## 1. Środowisko Pythona i wersja (zweryfikowane 2026-09-06)

Wniosek:
- Baseline `>=3.12`.
- Dev pin: **3.13** (`.python-version` = `3.13`).
- Format: `pyproject.toml` + `uv.lock` + `.python-version`. Zero `requirements.txt`, zero conda.

Struktura MVP:

```
portscanner/
  core/        # czysta logika, zero UI (importowalne z CLI/TUI/GUI)
    model.py       # modele portów, procesów, IP, Dockera, tuneli i migawki
    listeners.py   # TCP LISTEN + związane UDP bez peera
    procs.py       # PID -> name/cmdline, obsługa AccessDenied
    ips.py         # adresy interfejsów + jawny odczyt exit IP
    docker.py      # `docker ps` + projekcja inspect -> mapowania host:container
    cloudflared.py # proces + config.yml + metryki loopback przypisane PID
    k8s.py         # heurystyczne tagi po procesie/protokole/porcie
    snapshot.py    # scalanie źródeł i niezależne raporty błędów
    filtering.py   # wspólne filtry portów
    actions.py     # polityka kończenia procesów dla CLI/TUI
  cli.py       # typer/rich.table + --json + --kill
  presentation.py # wspólne komórki CLI/TUI, bez logiki odczytu
  tui/
    app.py         # Textual: tabela, workery, filtr, eksport
    dialogs.py     # dialog zgody na zakończenie procesu
```

Kontrakt po Fazie 3: [API core](core-api.md). Doprecyzowuje odczyty opcjonalnych
źródeł, pochodzenie danych i ograniczenia poniższych założeń MVP.

Zasada: **`core/` nie importuje niczego z `cli.py`/`tui/`**. Dzięki temu późniejsze GUI nie wymaga refaktoru.

---

## 2. Biblioteki (minimalne, uzasadnione; wersje: snapshot z PyPI 2026-09-06, do weryfikacji na starcie Fazy 0 — patrz §9)

| Biblioteka | Wersja live | Po co | Obowiązkowa? |
|---|---|---|---|
| `psutil` | `7.2.2` | `net_connections()`, `Process(name/cmdline/terminate)` — serce apki | TAK |
| `typer` (+ `rich` jako zależność) | `0.27.2` | CLI: komendy z type-hintów, `--help`, walidacja (ciągnie Clicka pod spodem) | TAK dla CLI |
| `textual` (+ `rich` jako zależność) | `8.2.8` / `rich 15.0.0` | TUI: tabela, filtr, sort, klawisze | TAK dla TUI |
| `pyyaml` | `6.0.3` | parsowanie `cloudflared config.yml` (ingress) | TAK, lekka |
| stdlib: `socket`, `ipaddress`, `subprocess`, `urllib` | — | local IP, `docker ps`, Global IP | TAK (bez depów) |
| `httpx` | `0.28.1` | alternatywa dla `urllib` do Global IP | NIE w MVP (stdlib wystarczy) |
| `docker-py` (SDK) | — | alternatywa dla CLI | NIE — odradzane w MVP (patrz §6) |

Czego **nie** brać w MVP: `scapy` (raw sockets/root), `nmap`/`python-nmap` (zewnętrzny binarz, AV go flaguje), `click` solo (mamy Typera — nie dublujemy).

### 2.1. Workflow `uv` (obowiązujący w tym repo)

```bash
uv python pin 3.13              # .python-version
uv init --bare --python 3.13    # lub ręczny pyproject.toml (ten projekt już istnieje)
uv add psutil pyyaml textual typer    # rich dociągnie się z textual/typera
uv sync                         # .venv + uv.lock
uv run portscanner --cli        # start CLI
uv run portscanner               # start TUI (domyślne)
uv lock --upgrade               # bump wersji celowy, nie z automatu
```

Zasady: zależności tylko przez `uv add`, nigdy ręczna edycja `uv.lock`. Bump textual/psutil świadomie przed releasem binarki (większa binarka = retest na Win/mac).


---

## 3. TUI vs CLI — różnice i wybór

| | CLI | TUI |
|---|---|---|
| Tryb | jednorazowy: `portscanner --cli --json`, koniec | interaktywny: tabela żyje, odświeżanie co 2 s |
| Użycie | skrypty, CI, `grep`, eksport | człowiek patrzy, filtruje, sortuje, ubija proces |
| Zależności | stdlib + psutil + typer/rich | + textual/rich (cięższe, większe binarki) |
| Testowanie/pakowanie | trywialne | trzeba testować render na 3 OS-ach |
| Automatyzacja | idealne (`--json`, kody wyjścia) | słabe |


---

## 4. Jak rozwiązać TUI, a jak CLI

### 4.1. CLI (Typer + Rich)

- `typer`: komendy z type-hintów, `portscanner --cli [--json] [--filter :8080]` lub `portscanner --cli --kill PID [--force]`, darmowy `--help` i walidacja.
- Render: `rich.table.Table` albo czysty `print` (żeby `--json | jq` działało bez ANSI — wykryj `isatty` / flagę `--no-color`).
- Tryb `--json`: wypisz `list[PortEntry]` jako JSON na stdout; raporty źródeł na stderr. Kod 0 przy udanym odczycie listeners, 1 przy jego błędzie (nawet gdy JSON zawiera częściowe dane), 2 przy błędnych argumentach. Szczegóły w [CLI](cli.md).
- Odświeżanie: brak (one-shot). Opcjonalnie `--watch 2` (pętla + `clear`).

### 4.2. TUI (Textual)

- Jeden ekran: `Header + Input(filtr) + DataTable + Footer`.
- Kolumny: `PROTO | BIND | PORT | PID | PROC | DOCKER (host->cont / compose proj.) | TUNNEL (hostname)`.
- Klawisze: `/` filtr, `s` sort po porcie/procesie, `k` kill (z potwierdzeniem), `r` refresh, `q` quit, `j` eksport JSON.
- Odświeżanie: `set_interval(2.0)` i worker, najwyżej jeden odczyt naraz. Diff po kluczu `(proto, bind, port, pid, origin)` zachowuje osobne procesy współdzielące port; zaznaczenie jest utrzymywane.
- Błąd uprawnień: raport źródła nad tabelą; nieznany PID jako `?`, status częściowego odczytu przy nazwie procesu. Bez podnoszenia uprawnień. Obsługa i ograniczenia: [TUI](tui.md).

Textual, nie `curses`: `curses` nie działa natywnie na Windows, Textual działa wszędzie.

---

## 5. Czy po MVP da się mieć CLI + TUI + GUI?

Tak, **pod warunkiem rozdziału z §1**. Wtedy:

- CLI i TUI to tylko dwa renderery tego samego `list[PortEntry]`.
- GUI to trzeci renderer — dokładasz warstwę UI, nie ruszasz `core/`.
- Wejście: `portscanner --gui`; w środowisku graficznym ikonka (`.desktop` / skrót w Menu Start / `.app`) odpala ten sam GUI — pod spodem zawsze ta sama logika `core/`.
- **Decyzja: GUI w `pywebview` + Vue** (lekkie — systemowy webview: WebKit/WebView2/GTK, bez bundlowanego Chromium; nowoczesny wygląd z ekosystemu Vue). Koszt: drugi toolchain (Node/npm/vite) **tylko** dla GUI + mostek JS↔Python. Dlatego GUI jako osobny target builda, nie osobna logika.
- Realizacja jako **Faza 7**, podzielona na szkielet aplikacji, połączenie z core,
  widok portów, operacje oraz weryfikację i dokumentację. Bieżący zakres to macOS;
  Windows/Linux po udostępnieniu środowisk. Szczegóły w [planie faz](plan-mvp.md).
- Odrzucone: `PySide6` (Qt = +150 MB do instalatora, mimo natywnego wyglądu), `Tkinter` (stdlib, ale archaiczny), `NiceGUI` (najszybszy prototyp, najsłabsze pakowanie — lokalny serwer FastAPI w dystrybucji).

Czego nie robić: nie pisać logiki zbierania w kodzie Textual ani Qt. Wszystko w `core/`, UI tylko wyświetla.

---

## 6. Czy aplikacja może "ubijać" procesy na portach?

W Fazie 4 wdrożono CLI i wspólną politykę w `core/actions.py`. Szczegóły
allowlisty, potwierdzeń i ograniczeń są w [CLI](cli.md). TUI korzysta z niej w Fazie 5.

- Mechanizm: `psutil.Process(pid).terminate()` (SIGTERM / `TerminateProcess`), po timeout `kill()` (SIGKILL) tylko za zgodą `--force`. Na Windows także `terminate()` kończy twardo. Każda operacja wymaga potwierdzenia w UI.
- Co musisz obsłużyć:
  - **Uprawnienia:** cudzy/SYSTEM proces = `AccessDenied`. Bez admina pokaż błąd, nie crash. Na Windows UAC, na Linux/macOS sudo.
  - **Blokowane:** PID 0/1, własny PID i przodkowie skanera, procesy infrastruktury (w tym `docker-proxy`, `kubelet/kube-apiserver`), cudzy użytkownik i procesy spoza allowlisty. `--force` nie znosi blokad. Dla dozwolonych procesów dialog pokazuje nazwę i argumenty; po zgodzie ponownie sprawdzamy tożsamość.
  - **Docker:** ubijanie `docker-proxy` nic nie da — port wróci. Dla kontenera pokaż `docker stop <name>` zamiast kill PID.
  - **`kubectl port-forward`:** kill PID działa, ale to jest sesja deweloperska — bezpieczne, pokaż komendę źródłową z cmdline.
- Wniosek: tak, `k` w TUI i `--kill PID` w CLI wchodzą do MVP razem z w pełni działającym TUI (decyzja z przeglądu planu 2026-09-06), ale z allowlistą i potwierdzeniem. Warunek "gotowe" = allowlista + dialog z §6, nie sam kod ubijania.

---

## 7. Czy wykryje porty K8s / K3s / MicroK8s?

Częściowo tak, w dwóch warstwach:

**Warstwa 1 (bez klastra, zawsze działa): proces + stałe porty.**
Wszystko to są zwykłe LISTEN, więc baza już je pokaże. Dopinasz heurystykę po nazwie procesu/portu:

- `kube-apiserver` → `6443`, `etcd` → `2379-2380`, `kubelet` → `10250`, `kube-proxy`, `containerd` → `1338`,
- `k3s server/agent` → `6443 + 8472 (flannel) + 10250`,
- `microk8s` (`kubelite`, `etcd`, `dqlite :19001`).

To wystarczy żeby w TUI pokazać tag `k8s/k3s/microk8s` zamiast gołego procesu.

**Warstwa 2 (z klastrem, gdy jest `kubeconfig`): pełne mapowanie.**
Jeśli `~/.kube/config` działa, wywołaj `kubectl get svc -A -o json` i nałóż `NodePort 30000-32767` oraz `port-forward` (parsuj cmdline `kubectl port-forward svc/x 8080:80`).
Bez dostępu do klastra tej warstwy nie ma — i to jest uczciwe ograniczenie, nie błąd.

W MVP: warstwa 1 (słownik `port/proces -> tag`). Warstwa 2 jako flaga `--kube` po MVP.

---

## 8. Najważniejsze kwestie "logiczne" (tu się wywraca większość takich narzędzi)

1. **LISTEN ≠ ESTABLISHED.** Dla TCP pokazuj tylko `LISTEN`; `ESTABLISHED` obejmuje także zaakceptowane połączenia serwera, nie tylko połączenia wychodzące. UDP ma osobną regułę z punktu 9.
2. **Efemeryczne vs serwery.** Nie filtruj po numerze portu: serwer może słuchać również na 49152–65535. TCP filtrujemy po stanie, UDP po związaniu i braku zdalnego adresu.
3. **Dual-stack IPv4/IPv6.** Grupuj wyłącznie parę `0.0.0.0` + `::` z tym samym znanym PID, protokołem i portem w `bind="*"` (port pozostaje osobnym polem). Nie łącz różnych/nieznanych PID ani konkretnych adresów. To grupowanie prezentacyjne, nie dowód ustawienia `IPV6_V6ONLY`; `group_dual_stack=False` zachowuje osobne adresy.
4. **Znaczenie BINDA:** `127.0.0.1:5432` = tylko lokalnie (bezpieczne), `0.0.0.0:5432` = z całej sieci/LAN (ryzyko), konkretne `192.168.1.10:3000` = tylko ten interfejs. To jest ważniejsza kolumna niż sam numer portu — pokaż ją wprost.
5. **Docker podwaja wiersze.** Mapowanie `0.0.0.0:8080->80` widać jako `docker-proxy` LISTEN na hoście + proces w kontenerze. Nie sumuj tego jako "2 usługi" — złącz w jeden wiersz `8080 (host) -> 80 (cont @web)`.
6. **Cloudflare Tunnel nie słucha.** `cloudflared` robi połączenie **wychodzące** do Cloudflare, więc nie ma LISTEN do znalezienia. Wykrywasz go tylko pośrednio: proces + `config.yml` (ingress `hostname -> localhost:PORT`) + metryki `:20241`. Brak procesu = brak tunelu, nawet jeśli DNS w Cloudflare dalej wskazuje na tunel.
7. **Uprawnienia tną widoczność.** Wiersze mogą mieć `pid=None`, a na Linuxie psutil może też pominąć niedostępne gniazda bez błędu. Na macOS odczyt całej listy wymaga root. Odmowa całego odczytu zgłasza `ListenerAccessDenied`, inne błędy systemowe `ListenerScanError`; UI ma je pokazać zamiast komunikatu o braku portów. Brak automatycznego podnoszenia uprawnień. Źródło: [psutil](https://psutil.io/api/#psutil.net_connections).
8. **Global IP kłamie za NAT/VPN.** Jawne `fetch_exit_ip()` odpytuje `api64.ipify.org` (IPv4/IPv6) i zwraca exit IP użytej trasy (VPN/proxy/operator CGNAT), nie "prawdziwe IP routera". Etykieta wyniku: `exit IP (widziane z internetu)`. Żądanie ujawnia usługodawcy adres wyjściowy; odczyty lokalne go nie wykonują. Timeout operacji gniazda domyślnie 3 s (nie twardy deadline DNS/całego wywołania), bez retry, błędy jako `ExitIPError`. W przyszłym TUI odczyt poza wątkiem renderowania.
9. **UDP.** Nie ma stanu `LISTEN`; psutil używa `CONN_NONE`. Pokazuj związane gniazda z niezerowym portem bez zdalnego adresu. Jest to heurystyka: może obejmować klientów używających `sendto`, a pomija gniazda ze stałym peerem. Oznacz `UDP (bez weryfikacji handshake)`; nie wysyłaj pakietów w celu weryfikacji.

---

## 9. Decyzje do zaklepania przed kodem

- [x] Baseline `>=3.12`, dev pin `3.13` (zweryfikowane: 3.9 martwy, 3.10 umiera 2026-10-31, 3.14 za nowy do pakowania).
- [x] Manager: **`uv`** (`uv python pin/add/sync/run`, lock w `uv.lock`). Lokalnie `uv 0.12.10`.
- [x] Stack UI: **CLI = Typer + Rich, TUI = Textual** (decyzja zamiast argparse; patrz §2–§4).
- [x] GUI po MVP: **pywebview + Vue** (lekkie, systemowy webview; Node tylko dla GUI; patrz §5).
- [x] Jakość kodu: **Ruff** (lint + format) + **Pyrefly** (typecheck) od pierwszego kodu (patrz §11).
- [x] Docker do developmentu: **NIE** — decyzja z 2026-09-06 (patrz §10).
- [ ] MCP Python SDK jako kolejny renderer `core/` — dopiero po stabilizacji, nie w MVP (patrz §12).
- [x] Conventional Commits: **wymagane** — lefthook (`lefthook.yml` + `scripts/check_commit_msg.py`) lokalnie.
- [x] Wejście: `portscanner` → TUI, `--cli` → CLI, `--gui` → GUI po MVP (ikonka desktopowa odpala ten sam GUI na tym samym `core/`; szczegóły w `docs/plan-mvp.md`).
- [x] Testy: `pytest` (unit `core/` + `CliRunner` dla `--json` + Textual `Pilot` smoke dla TUI) + matryca manualna Win/Linux/Mac.
- [x] CI docelowo: self-hosted Actions (Ubuntu x86 + RPi 5B ARM64, przy okazji test ARM64); status: maszyny w przygotowaniu, do tego czasu matryca manualna.
- [x] Dystrybucja MVP: `pipx` (`pipx install git+...`), binarki (PyInstaller) dopiero po stabilizacji.
- [x] Docker jako źródło danych: **CLI** (`docker ps --format json`), nie SDK — zero depów, stabilny format wyjścia, brak dryfu wersji API daemona; SDK (`docker-py`) ma sens dopiero przy orkiestracji (start/stop/stream logów), nie do odczytu listy.
- [x] K8s tylko warstwa 1 (tagi) w MVP; warstwa 2 (`--kube`) po MVP.
- [x] Wersje: **płynne** — snapshot z §2 to punkt odniesienia z 2026-09-06; na starcie Fazy 0 bierzemy najnowsze stabilne (`uv lock`), bump później tylko świadomy przed releasem.

---

## 10. Jakość kodu: Ruff + Pyrefly (decyzja)

**Decyzja: Ruff (lint + format) obowiązkowy od pierwszego kodu, Pyrefly (typecheck) od pierwszego kodu, `core/` docelowo bez ani jednego błędu typów.**

```bash
uv add --dev ruff pyrefly   # dev-deps, nie wchodzą do binarki
uv run ruff check .         # lint
uv run ruff format .        # format (zamiast Black/isort — Ruff robi obie rzeczy)
uv run pyrefly check        # typecheck
```

Konfiguracja w `pyproject.toml` (jak powstanie):

```toml
[tool.ruff]
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pyrefly]
# search-path albo venv wykrywane automatycznie; zaostrzać w razie potrzeby
```

Uwagi:
- Ruff zastępuje flake8 + Black + isort jednym binarkiem — mniej depów do pakowania.
- Pyrefly (checker Mety, napisany w Ruście) zamiast Pyrighta: **zero Node w runtime**, binarka z PyPI, bardzo szybki. Świadoma zamiana z 2026-09 — Pyright wymaga Node, bo sam jest napisany w TS.
- Ruff jest blokującym jobem `pre-commit` od Fazy 0 (Pyrefly uruchamiany ręcznie na koniec każdej fazy).

---

## 11. Integracja MCP (po stabilizacji, NIE w MVP)

**Kierunek: wystawić `core/` jako serwer MCP (Python SDK `mcp`), żeby agenci AI mogli pytać o porty, procesy i tunele.**

Dlaczego to pasuje bez refaktoru: `core/` nie importuje UI (§1), a CLI `--json` już definiuje kontrakt (`list[PortEntry]`). MCP to po prostu czwarty renderer — obok CLI/TUI/GUI (§5). Szkic (API SDK z 2026-09, do weryfikacji przed implementacją):

```python
from mcp.server.mcpserver import MCPServer
from portscanner.core import listeners  # ten sam core co CLI/TUI

mcp = MCPServer("portscanner")


@mcp.tool()
def list_listen_ports() -> str:
    """Zwróć porty LISTEN hosta jako JSON (jak `portscanner --cli --json`)."""
    ...
```

Start: `uv add mcp`, transport `stdio` (`mcp.run()`), podpięcie w kliencie (np. wpis `stdio` w `.vscode/mcp.json`).

Warunki brzegowe (dlatego po MVP):
- Najpierw stabilne `core/` + `--json` + testy — MCP tylko to wystawia, nic nie zbiera sam.
- Narzędzia tylko do odczytu jako domyślne; `kill` (jeśli w ogóle) wyłącznie za wyraźnym potwierdzeniem po stronie agenta — ta sama allowlista co w §6.
- Bezpieczeństwo: serwer `stdio` (lokalny), bez `sse`/`http` w pierwszej wersji.
