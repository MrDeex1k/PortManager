# Historia zmian

## W przygotowaniu — Faza 7 zakończona na macOS (2026-09-12)

- Opcjonalne `--gui`: okno pywebview i Vue, lokalne zasoby w wheel.
- Rzeczywiste migawki core w GUI: porty, procesy, lokalne IP, Docker/Compose,
  tunele, tagi, raporty źródeł i odświeżanie co 2 sekundy.
- Wspólne filtry core, sortowanie TanStack Table oraz pełny inspektor danych.
- Natywny eksport widocznego widoku w kontrakcie JSON CLI/TUI.
- Potwierdzane kończenie dozwolonych procesów z jednorazową zgodą,
  ponowną weryfikacją celu i jawnym force.
- Bun + Vite + Tailwind 4 przez plugin Vite; kontrola Vue przez Node/vue-tsc.
- Grafitowa paleta z błękitnolawendowym akcentem i własna ikona PNG/ICNS.
- Generator lekkiego `PortManager.app` z ikoną, dostępny po instalacji wheel
  jako `portscanner-macos-app`.
- Zweryfikowano 285 zaliczonych testów Python (dodatkowo 1 pominięty),
  3 testy Bun, kontrole typów i formatowania oraz pełny natywny przepływ GUI
  z wheel poza repozytorium. Nie opublikowano wydania.

## 0.1.0 — MVP przygotowane lokalnie (2026-09-08)

- Wspólny core odczytuje lokalne TCP LISTEN, związane UDP, dane procesów
  i adresy interfejsów. Opcjonalnie rozpoznaje publikacje Docker/Compose,
  konfiguracje i metryki cloudflared oraz heurystyczne tagi K8s.
- Domyślny TUI ma filtr, sortowanie, odświeżanie w tle, raporty źródeł
  i eksport widocznej migawki do JSON bez nadpisywania plików.
- Jednorazowe CLI obsługuje tabelę, JSON, filtry, wyłączanie źródeł
  oraz jawny odczyt exit IP. Raporty trafiają na stderr.
- Kończenie własnego procesu wymaga allowlisty, weryfikacji tożsamości
  i zgody w CLI/TUI. Force pozwala na eskalację dopiero po timeout.
- Znane argumenty uwierzytelniające są maskowane w migawkach, JSON
  i potwierdzeniach, bez osłabiania ponownej weryfikacji celu operacji.
- Nieparsowalne adresy nie przerywają pozostałych odczytów, a próby metryk
  jednego procesu dzielą wspólny budżet czasu.
- Pakowanie: sdist i wheel, instalacja przez pipx. Skrypt weryfikuje
  zbudowany wheel poza repozytorium i bez zmiany instalacji użytkownika.

Zweryfikowano macOS ARM64 z Pythonem 3.12, 3.13 i 3.14. Windows i Linux
czekają na środowiska testowe zgodnie z decyzją użytkownika. Ograniczenia
oraz dowody weryfikacji: [wydanie i matryca](docs/release.md).

To lokalne przygotowanie wydania; tag ani GitHub Release nie zostały opublikowane.
