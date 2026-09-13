"""Eksport rozmiarów ICNS z gotowej ikony PNG; narzędzia systemowe macOS."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend/public/icons/portmanager.png"
OUTPUT = ROOT / "portscanner/gui/icons/portmanager.icns"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="portmanager-icon-") as directory:
        iconset = Path(directory) / "PortManager.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = str(size * scale)
                suffix = "@2x" if scale == 2 else ""
                destination = iconset / f"icon_{size}x{size}{suffix}.png"
                subprocess.run(
                    [
                        "sips",
                        "-z",
                        pixels,
                        pixels,
                        str(SOURCE),
                        "--out",
                        str(destination),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(OUTPUT)], check=True
        )
    print(OUTPUT)


if __name__ == "__main__":
    main()
