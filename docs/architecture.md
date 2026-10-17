# Architektura PortManager

PortManager łączy lokalne porty z procesami, kontenerami i tunelami.
CLI, TUI i GUI korzystają ze wspólnego modelu oraz tych samych reguł odczytu,
filtrowania i operacji na procesach.

## Przepływ danych

```text
System · Docker CLI · cloudflared · kubectl (opcjonalnie)
                           │
                   portscanner/core
                migawki · filtry · operacje
                           │
            ┌──────────────┼──────────────┐
           CLI            TUI            GUI
       Typer + Rich     Textual     pywebview + Vue
```

`core/` nie importuje interfejsów. Modele są niemutowalnymi dataclasses,
a `collect_snapshot()` zwraca dane wraz z raportem każdego źródła.
Brak wyników po udanym odczycie jest odróżniany od błędu lub odmowy dostępu.
Awaria źródła opcjonalnego nie usuwa wyników pozostałych źródeł.

## Podział odpowiedzialności

| Moduł | Odpowiedzialność |
|---|---|
| `core/model.py` | Modele gniazd, procesów, powiązań i raportów |
| `core/listeners.py`, `procs.py`, `ips.py` | Odczyt systemowy przez psutil i adresy IP |
| `core/docker.py`, `cloudflared.py`, `k8s.py` | Publikacje kontenerów, reguły tuneli i tagi heurystyczne |
| `core/kube.py`, `kube_command.py`, `kube_cache.py` | Odczyt klastra, kontrola podprocesów i cache |
| `core/snapshot.py`, `filtering.py` | Scalanie źródeł i wspólna składnia filtrów |
| `core/actions.py` | Weryfikacja celu i reguły kończenia procesów |
| `presentation.py`, `cli.py`, `tui/` | Prezentacja w terminalu i obsługa interakcji |
| `gui/`, `frontend/src/` | Mostek Python–JavaScript i interfejs Vue |

## Decyzje techniczne

- **psutil do odczytu lokalnego.** Aplikacja odczytuje stan systemu bez aktywnego
  skanowania portów zdalnych hostów. TCP LISTEN i związane UDP mają odrębną semantykę.
- **Docker przez CLI.** Strukturalne dane `docker ps` i `docker inspect` są
  odczytywane przez lokalny socket lub pipe. PID z kontenera nie jest
  przypisywany do procesu hosta na podstawie samego numeru portu.
- **Textual do TUI.** Workery oddzielają odczyty od interakcji. Aktualizowane
  są zmienione wiersze, a stabilny klucz zachowuje zaznaczenie.
- **pywebview do desktopu.** Systemowy webview wyświetla lokalnie zbudowany
  frontend Vue. Dodatek GUI jest opcjonalny; CLI i TUI nie wymagają Bun ani Node.
- **TanStack Query i Table.** Frontend zarządza cyklem odczytu, sortowaniem
  i wyborem wierszy, a filtry tekstowe w trybie desktopowym wykonuje core.
- **Osobny cache Kubernetes.** Odczyt klastra co 30 s nie blokuje lokalnych
  odświeżeń co 2 s. Błąd zachowuje poprzednie mapowania z jawnym statusem i wiekiem.

## Operacje na procesach

Odczyt migawki nigdy nie kończy procesu. `prepare_kill()` sprawdza właściciela,
allowlistę, chronione procesy i tożsamość celu. Po potwierdzeniu przez użytkownika
`terminate_target()` ponownie weryfikuje warunki przed sygnałem.
GUI przechowuje cel pod krótkotrwałym, jednorazowym tokenem; zmiana zaznaczenia
nie zmienia celu otwartego dialogu.

Znane flagi uwierzytelniające są maskowane w prezentowanych argumentach i JSON.
Maskowanie nie obejmuje dowolnych sekretów w argumentach pozycyjnych lub URL.
[Pełne reguły operacji](cli.md#kończenie-procesu).

## Granice danych

Migawka nie jest atomowa. Dostęp do gniazd i szczegółów procesów zależy od
uprawnień systemu. Publikacja Docker, NodePort, reguła tunelu i tag heurystyczny
opisują różne rodzaje dowodów; nie są wspólnym potwierdzeniem osiągalności usługi.
Kubernetes kontaktuje się z wybranym klastrem wyłącznie po włączeniu tej integracji.
Exit IP jest oddzielnym żądaniem do zewnętrznej usługi.

Dalsze informacje: [API core](core-api.md) · [Kubernetes](kubernetes.md) ·
[platformy i instalacja](release.md) · [rozwój i testy](development.md).
