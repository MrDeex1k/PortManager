# Historia zmian

Historia opisuje zmiany w repozytorium. Uruchomienie ze źródeł i instalację
lokalnego pakietu opisuje [dokumentacja instalacji](docs/release.md).

## Poprawki modeli, odczytów i operacji — 2026-11-05

- Pełne informacje o connectorach Tunnel w GUI, jednoznaczne argumenty procesu
  i klucze mapowań Docker uwzględniające IPv4/IPv6.
- Generowane kontrakty Python/TypeScript, kody błędów mostka i strukturalna
  świeżość cache Kubernetes.
- Izolowanie natywnych błędów psutil, częściowy odczyt dostępnych procesów na macOS,
  jawnie nieznany peer UDP i normalizacja nieznanego właściciela na Windows.
- Indeksowane scalanie źródeł, relacje tuneli dla NodePort, normalizacja stref IPv6
  oraz wspólne przypadki testowe filtrów z obsługą Unicode.
- Maskowanie sąsiadujących flag sekretów i ponowna zgoda na eskalację po timeoutcie,
  także po zamknięciu portu. Anulowane i wygasłe zgody usuwają cel z pamięci GUI.
- Potwierdzenie twardego zakończenia na Windows oraz neutralny wynik zniknięcia
  zweryfikowanego procesu podczas eskalacji.

## Zależności — 2026-10-17

- Aktualizacja bezpośrednich i przechodnich zależności Pythona oraz frontendu.
- Typer 0.27.3, Pyrefly 1.4.0 i Ruff 0.17.1.
- Vue 3.5.44, TanStack Table 9.3.1, Vue Query 5.104.3, Vite 8.3.4 i vue-tsc 3.3.13.
- Runner Bun 1.4.3; TypeScript 6.0.3 zgodny z używaną wersją vue-tsc.

## Odświeżanie Kubernetes — 2026-10-08

- Odczyt klastra w tle co 30 s w GUI i TUI, niezależnie od lokalnych skanów.
- Wiek danych oraz zachowanie poprzednich mapowań po błędzie odświeżenia.
- Ręczne odświeżanie omijające cache i unieważnianie danych po zmianie lokalnych IP.
- Przełącznik Kubernetes w GUI, także po uruchomieniu aplikacji z Findera.
- Wyszukiwanie pól Kubernetes i przykłady NodePort oraz port-forward w podglądzie.
- Sprzątanie potomnych procesów pluginów kubectl przez Job Object na Windows.

## Integracja Kubernetes — 2026-10-03

- Opcjonalne `--kube` we wszystkich interfejsach, z odczytem usług i węzłów przez kubectl.
- NodePort dla węzłów o lokalnym IP oraz rozpoznawanie lokalnych sesji port-forward.
- Pole `kubernetes` w JSON i `origin="kubernetes"` dla konfiguracji bez PID hosta.
- Wspólny filtr, prezentacja CLI/TUI i inspektor Kubernetes w GUI.
- Pojedynczy odczyt services/nodes, limit wyjścia i sprzątanie procesów potomnych.
- Karencja publikacji nowych zależności wynosząca 3 godziny dla Bun i uv.

## Interfejs desktopowy — 2026-09-12

- Opcjonalny tryb `--gui` oparty na pywebview i Vue, z zasobami frontendu w wheel.
- Migawki portów, procesów, lokalnych IP, Docker/Compose, tuneli i tagów.
- Odświeżanie co 2 s, wspólne filtry, sortowanie oraz inspektor portu.
- Natywny eksport widocznych danych do JSON.
- Potwierdzane kończenie dozwolonych procesów z jednorazowym tokenem zgody
  i ponowną weryfikacją celu.
- Frontend oparty na Bun, Vite, Tailwind CSS i TanStack Query/Table.
- Własna ikona PNG/ICNS i generator skrótu `PortManager.app`.

## Podstawowa wersja 0.1.0 — 2026-09-08

- Wspólny core odczytujący TCP LISTEN, związane UDP, procesy i adresy interfejsów.
- Publikacje Docker/Compose, lokalne konfiguracje i metryki cloudflared oraz tagi K8s.
- Domyślny TUI z filtrem, sortowaniem, odświeżaniem w tle i eksportem JSON.
- Jednorazowe CLI z tabelą, JSON, filtrami, wyborem źródeł i jawnym odczytem exit IP.
- Kończenie własnych procesów z allowlistą, potwierdzeniem i kontrolowaną eskalacją.
- Maskowanie znanych flag uwierzytelniających w migawkach, JSON i dialogach.
- Niezależne raporty źródeł i obsługa częściowych danych.
- Dystrybucja sdist/wheel oraz weryfikacja instalacji przez pipx poza repozytorium.
