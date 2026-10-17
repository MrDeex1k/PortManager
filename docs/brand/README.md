# Identyfikacja wizualna

Ikona PortManager przedstawia trzy połączone porty na grafitowej płytce.
Interfejs używa grafitowego tła i błękitnolawendowego akcentu `#a9b8f5`.
Pliki PNG mają nieprzezroczyste tło.

## Zasoby

| Plik | Zastosowanie |
|---|---|
| [portmanager-source.png](portmanager-source.png) | Grafika źródłowa, 1254 × 1254 |
| [portmanager.png](../../frontend/public/icons/portmanager.png) | Ikona 1024 × 1024 |
| [portmanager-128.png](../../frontend/public/icons/portmanager-128.png) | Ikona interfejsu |
| [portmanager-64.png](../../frontend/public/icons/portmanager-64.png) | Favicon |
| [portmanager.icns](../../portscanner/gui/icons/portmanager.icns) | Zestaw rozmiarów dla macOS |

## Regenerowanie ICNS

Z katalogu głównego repozytorium na macOS:

```bash
uv run --locked python scripts/build_gui_icon.py
```

Skrypt korzysta z systemowych `sips` i `iconutil`. Źródłem jest PNG 1024 × 1024
w `frontend/public/icons/portmanager.png`.
