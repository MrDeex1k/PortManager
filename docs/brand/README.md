# Ikona PortManager

Grafitowa, zaokrąglona płytka z błękitnolawendowym symbolem trzech połączonych
portów. Paleta odpowiada zatwierdzonemu prototypowi. Bez liter i zielonej poświaty.

- `portmanager-source.png`: oryginalny wynik generatora, 1254 × 1254.
- `frontend/public/icons/portmanager.png`: eksport 1024 × 1024.
- `frontend/public/icons/portmanager-128.png`: ikona w interfejsie.
- `frontend/public/icons/portmanager-64.png`: favicon.
- `portscanner/gui/icons/portmanager.icns`: zestaw rozmiarów dla macOS.

Źródło powstało przez wbudowane narzędzie **image_gen**, bez CLI/API.
Finalny PNG jest nieprzezroczysty, z ciemnym tłem zewnętrznym.
Próbę wersji z alfa odrzucono, bo generator narysował szachownicę zamiast
kanału przezroczystości. Do pakietu wchodzi wyłącznie wersja z ciemnym tłem.
Rozmiary eksportowano przez `sips`, ICNS przez `iconutil`.
Powtórzenie eksportu ICNS na macOS: `uv run python scripts/build_gui_icon.py`.

## Prompt projektu

Use case: logo-brand. Asset type: production macOS desktop app icon for
PortManager, a local network port and process manager. Create ONE exceptionally
polished, restrained app icon, square 1024x1024, straight-on orthographic front
view. A graphite charcoal rounded square (macOS squircle) with subtle tactile
ceramic material, softly beveled edges and a tiny restrained highlight. Center
one bold memorable geometric glyph: three rounded rectangular port sockets
connected by a single elegant branching line, arranged as a clear compact
network symbol with one upper central socket and two lower sockets. Glyph in
pale periwinkle blue with a slight lavender undertone, close to #a9b8f5. Graphite
background close to #181b22. The connected port glyph should have just enough
shallow embossed depth to feel like a crafted native application icon; highly
legible at small sizes, generous internal breathing room, balanced silhouette.
Transparent background outside the squircle, no external backdrop. Icon occupies
about 88% of canvas centered. No letters, no text, no wordmark, no numbers, no
green, no neon, no glow, no lens effects, no decorative circuitry, no wire
clutter, no multiple icons, no mockup presentation, no surrounding UI. Quiet
premium developer tool aesthetic, original design.

## Finalna korekta tła

Change ONLY the exterior backdrop outside the rounded dark app icon to perfectly
solid dark charcoal RGB(16,17,19) hex #101113. There must be absolutely no
checkerboard, no white pixels, no light backdrop anywhere outside the icon.
Preserve the graphite rounded icon tile and all periwinkle network-port glyph
details EXACTLY. Same square composition. Deliver a clean opaque PNG app icon
on a perfectly flat #101113 exterior background. Do not change the symbol.
Do not include any transparency visualization.
