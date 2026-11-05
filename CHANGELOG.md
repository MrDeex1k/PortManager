# Historia zmian

Historia opisuje zmiany w repozytorium. Uruchomienie ze źródeł i instalację
lokalnego pakietu opisuje [dokumentacja instalacji](docs/release.md).

## Poprawki pakowania i wydań — 2026-11-05

- Izolowany build CLI/TUI lub GUI ze świeżym frontendem i weryfikacją archiwum
  przed opublikowaniem artefaktów; jawna lista zawartości sdist.
- Weryfikacja metadanych, punktów wejścia i lokalnych zasobów wheel, opcje
  `--inspect-only` i `--gui` oraz instalacja dodatku GUI w tymczasowym pipx.
- Poprawna obsługa częściowych odczytów CLI w smoke instalacji i izolacja
  konfiguracji pip/pipx; brak limitu pięciu minut dla sesji interaktywnej.
- Odmowa publikacji skrótu `.app` pod dowiązaniem symbolicznym i PATH dla narzędzi
  uruchamianych z Findera.
- Usunięcie źródłowego PNG 1024 px z zasobów runtime GUI (około 1,25 MB mniej
  nieskompresowanych danych); atomowe generowanie ICNS z timeoutami narzędzi.

## Poprawki mostka desktopowego i Vue — 2026-11-05

- Jawna lista operacji Python–JS zamiast wystawiania obiektu backendu,
  bezpieczne błędy oraz odrzucanie wywołań i spóźnionych migawek po zamknięciu.
- Atomowy, strumieniowy eksport JSON z blokadą równoległych dialogów, ścisłą
  walidacją generacji i prywatnymi uprawnieniami pliku na POSIX.
- Rozdzielenie danych demo od pierwszego odczytu desktopowego, obsługa błędów
  filtra i ochrona ustawienia Kubernetes przed spóźnionymi metadanymi.
- Blokada Escape podczas operacji na procesie i unieważnianie spóźnionych zgód.
- Poprawne kopiowanie endpointów IPv6 oraz oznaczenia dostępności dialogów,
  filtrów i sortowania.
- Strony po 100 wierszy ograniczające rozmiar DOM dużych list; eksport nadal
  zapisuje wszystkie wyniki filtra w aktualnej kolejności sortowania.
- Testy regresyjne granicy mostka i komponentów Vue oraz rozszerzony smoke GUI.

## Poprawki CLI i TUI — 2026-11-05

- Rozróżnienie ograniczenia informacji o peerze UDP na Windows od niepełnego
  odczytu gniazd w kodzie wyjścia CLI.
- Prezentacja wszystkich connectorów Cloudflare Tunnel i kodów diagnostycznych
  w obu interfejsach terminalowych.
- Opcje `--json-snapshot` i `--columns`, walidacja zakresu timeoutu oraz jawnych
  opcji równych wartości domyślnej.
- Strumieniowy eksport JSON przy zachowaniu dotychczasowego formatu listy portów.
- Przewijane klawiaturą panele TUI i pełny widok diagnostyki pod `d`.
- Zapamiętywanie odświeżenia podczas skanu, również po zakończeniu procesu,
  działające Ctrl+Q w filtrze oraz pomijanie formatowania niezmienionych wierszy.

## Poprawki Docker, Tunnel i Kubernetes — 2026-11-05

- Zachowanie częściowych wyników Docker inspect, obsługa publikacji routed,
  ścisłe typy bindingów oraz wspólny budżet czasu i limit wyjścia poleceń.
- Poprawne rozpoznawanie opcji connectorów, usług wbudowanych, bastionMode,
  tokenów w YAML/środowisku i adresów quick tunnel bez schematu.
- Ograniczony czasowo odczyt zwykłych plików konfiguracji, przerywanie powolnego
  HTTP metryk i wspólny budżet I/O wszystkich connectorów.
- Cache Kubernetes powiązany z rewizją kubeconfig, przypięty kontekst NodePort,
  zapamiętywanie ręcznego odświeżenia i projekcja potrzebnych pól kubectl.
- Nadzór nad zaobserwowanymi odłączonymi potomkami na POSIX, anulowalne odczyty
  potoków oraz jawny opis ograniczeń sprzątania procesów.
- Strukturalne kody diagnostyczne źródeł i connectorów w kontrakcie Python/TypeScript.

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
