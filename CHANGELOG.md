# Historia zmian

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
- Pakowanie: sdist i wheel, instalacja przez pipx. Skrypt weryfikuje
  zbudowany wheel poza repozytorium i bez zmiany instalacji użytkownika.

Zweryfikowano macOS ARM64 z Pythonem 3.12, 3.13 i 3.14. Windows i Linux
czekają na środowiska testowe zgodnie z decyzją użytkownika. Ograniczenia
oraz dowody weryfikacji: [wydanie i matryca](docs/release.md).

To lokalne przygotowanie wydania; tag ani GitHub Release nie zostały opublikowane.
