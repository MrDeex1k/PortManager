# GUI desktopowe

Desktopowy PortManager wyświetla rzeczywiste migawki systemu we frontendzie Vue
uruchomionym przez pywebview. Zwykły podgląd Vite w przeglądarce używa jawnie
oznaczonych danych demonstracyjnych.

## Uruchomienie

Z katalogu głównego repozytorium:

```bash
uv sync --locked --extra gui
cd frontend
bun install --frozen-lockfile
bun run build
cd ..
uv run --locked --extra gui portscanner --gui
```

CLI i TUI nie wymagają dodatku GUI ani narzędzi frontendu. Wymagania środowiska,
instalacja przez pipx i zakres zgodności: [instalacja i pakowanie](release.md).

## Praca z portami

- Wybierz wszystkie porty lub widok Docker, tuneli albo Kubernetes.
- Filtruj tekstowo, przez dokładny port `:8080` lub PID `pid:8421`.
  Filtr tekstowy w trybie desktopowym korzysta ze wspólnego core.
- Wybierz TCP lub UDP i sortuj tabelę nagłówkami kolumn.
- Kliknij port, aby zobaczyć bind, PID, dostępne argumenty procesu,
  mapowania kontenerów, projekt i usługę Compose, tunele oraz kontekst Kubernetes.
- Użyj „Odśwież”, aby zlecić odczyt, albo pozostaw automatyczne odświeżanie co 2 s.
  Zaznaczenie jest zachowywane po kluczu `(proto, bind, port, pid, origin)`.

Inspektor znajduje się obok tabeli, a przy węższym oknie przechodzi pod nią.
Interfejs odróżnia pierwszy odczyt, brak wyników, brak dopasowań, dane częściowe
i błąd. Raport odmowy uprawnień nie oznacza braku portów.

Connectory Cloudflare Tunnel są prezentowane także bez znanych tras: z PID,
statusem konfiguracji, metryk i liczbą połączeń. Argumenty procesu są tablicą JSON;
„Brak argumentów” odróżnia pustą listę od niedostępnych danych.

## Kubernetes

Dodaj `--kube` przy uruchomieniu lub użyj przełącznika „Włącz Kubernetes”
w widoku Kubernetes. Ustawienie dotyczy bieżącej sesji i jest dostępne także
po uruchomieniu skrótu z Findera. Domyślnie odczyt klastra jest wyłączony.

Odczyt NodePort działa w tle co 30 s; lokalne dane port-forward są aktualizowane
przy skanach systemu. Widok pokazuje wiek danych. Awaria klastra zachowuje
poprzednie mapowania z raportem `partial`; ręczne odświeżenie omija cache.
[Konfiguracja i interpretacja mapowań](kubernetes.md).

## Eksport i operacje

**„Eksportuj widok”** zapisuje widoczne wiersze w aktualnej kolejności jako
JSON o tym samym kontrakcie `PortEntry[]` co CLI i TUI. Natywny dialog pozwala
wybrać ścieżkę i potwierdzić zastąpienie pliku. Raporty źródeł i lokalne IP
nie wchodzą do tej tablicy; przy błędzie źródła wynik może być częściowy.

**Kończenie procesu** wymaga weryfikacji i potwierdzenia w dialogu. Cel jest
przechowywany pod krótkotrwałym, jednorazowym tokenem. Zmiana zaznaczenia
nie zmienia celu dialogu; przed sygnałem core ponownie sprawdza jego tożsamość
i reguły. Force jest domyślnie wyłączone. Po timeoutcie dialog pozwala osobno
potwierdzić eskalację, również gdy proces zamknął port. Na Windows dialog
informuje o twardym zakończeniu i nie oferuje pozornego łagodnego trybu.
Anulowanie usuwa zapisany cel, a timer usuwa nieużyte zgody po 120 sekundach.
[Allowlista i reguły operacji](cli.md#kończenie-procesu).

Znane flagi uwierzytelniające są maskowane w argumentach i eksporcie;
nie obejmuje to dowolnych sekretów w treści argumentów.
[Zakres maskowania](core-api.md#prywatność-argumentów-procesów).

## Skrót PortManager.app

Po instalacji wheel z dodatkiem GUI, gdy `portscanner` jest dostępny na PATH:

```bash
portscanner-macos-app \
  --command "$(command -v portscanner)" \
  --output "$HOME/Applications/PortManager.app"
open "$HOME/Applications/PortManager.app"
```

Generator tworzy ikonę ICNS, `Info.plist` i launcher wykonujący `portscanner --gui`.
Odmawia zastąpienia istniejącej ścieżki. Nie kopiuje interpretera ani zależności:
wskazane środowisko musi pozostać w tej samej lokalizacji. Bundle jest niepodpisany
i nie jest samodzielnym instalatorem aplikacji.

## Podgląd i development

Sam interfejs z danymi demo uruchomisz przez `bun run dev` w katalogu `frontend`.
Odczyt systemu i operacje na procesach wymagają mostka desktopowego.

Do pracy z aktualizacją frontendu na żywo uruchom dwa terminale, oba z katalogu
repozytorium. W pierwszym:

```bash
cd frontend
bun run dev
```

W drugim, po synchronizacji środowiska z dodatkiem GUI:

```bash
PORTSCANNER_GUI_DEV_URL=http://127.0.0.1:5173 uv run --locked --extra gui portscanner --gui
```

Mostek akceptuje tylko ten adres loopback i port. Gotowa aplikacja ładuje lokalne
zasoby z `portscanner/gui/assets/` i nie wymaga działającego Vite.
Wersje zależności znajdują się w [package.json](../frontend/package.json),
[pyproject.toml](../pyproject.toml) oraz lockfile'ach.

Dalsze informacje: [rozwój i testy](development.md) · [architektura](architecture.md) ·
[identyfikacja wizualna](brand/README.md).

Kontrakt mostka obejmuje typowane odpowiedzi i strukturalne kody błędów
(`stale_snapshot`, `invalid_filter`, `consent_expired`, `termination_pending`,
`busy` itd.). Pola raportów `last_success_at`, `age_seconds`, `stale` i `refreshing`
pozwalają prezentować świeżość bez parsowania komunikatów.
