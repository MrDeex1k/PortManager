"""Sprawdź wheel i instalację pipx poza repo, bez zmiany instalacji użytkownika.

--inspect-only sprawdza archiwum bez pobierania zależności i uruchamiania aplikacji.
"""

import argparse
import configparser
import hashlib
import os
import platform
import posixpath
import shutil
import subprocess
import sys
import zipfile
from email.parser import Parser
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit


class AssetLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.has_module = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        link = attributes.get("src" if tag == "script" else "href")
        if tag in ("script", "link") and link:
            self.links.append(link)
        if tag == "script" and attributes.get("type") == "module" and link:
            self.has_module = True


def inspect_wheel(wheel: Path, *, require_gui: bool = False) -> bool:
    """Validate identity, entry points and local assets referenced by GUI HTML."""
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("Wheel musi zawierać dokładnie jeden plik METADATA.")
        info = Parser().parsestr(archive.read(metadata[0]).decode("utf-8"))
        if info.get("Name") != "portscanner" or not info.get("Version"):
            raise ValueError("Wheel nie jest wydaniem portscanner.")
        prefix = metadata[0].removesuffix("METADATA")
        entries = configparser.ConfigParser(interpolation=None)
        entries.read_string(archive.read(prefix + "entry_points.txt").decode("utf-8"))
        expected = {
            "portscanner": "portscanner.cli:main",
            "portscanner-macos-app": "portscanner.gui.macos_app:main",
        }
        if not entries.has_section("console_scripts") or any(
            entries["console_scripts"].get(key) != value
            for key, value in expected.items()
        ):
            raise ValueError("Wheel ma nieprawidłowe punkty wejścia.")
        required = {
            "portscanner/__init__.py",
            "portscanner/cli.py",
            "portscanner/tui/app.py",
            "portscanner/gui/macos_app.py",
            "portscanner/gui/icons/portmanager.icns",
        }
        if not required <= names:
            raise ValueError("Wheel nie zawiera wymaganych modułów lub ikony.")
        assets = "portscanner/gui/assets/"
        has_gui = any(name.startswith(assets) for name in names)
        if require_gui and not has_gui:
            raise ValueError("Wheel nie zawiera GUI. Zbuduj wydanie z --gui.")
        if has_gui:
            index = assets + "index.html"
            if index not in names:
                raise ValueError("Brak index.html w zasobach GUI.")
            html = AssetLinks()
            html.feed(archive.read(index).decode("utf-8"))
            if not html.has_module:
                raise ValueError("HTML GUI nie wskazuje modułu JavaScript.")
            for link in html.links:
                parsed = urlsplit(link)
                path = unquote(parsed.path)
                resolved = posixpath.normpath(assets + path)
                if (
                    parsed.scheme
                    or parsed.netloc
                    or path.startswith("/")
                    or not resolved.startswith(assets)
                    or resolved not in names
                ):
                    raise ValueError(
                        f"Brak lokalnego zasobu GUI lub nieprawidłowy URL: {link}"
                    )
            if assets + "icons/portmanager-128.png" not in names:
                raise ValueError("Brak ikony interfejsu GUI.")
        return has_gui


def isolated_environment(root: Path) -> dict[str, str]:
    """Retain index/certificate settings, but never pip installation destinations."""
    index_options = {
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "PIP_CERT",
        "PIP_CLIENT_CERT",
        "PIP_NO_INDEX",
        "PIP_FIND_LINKS",
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "PIPX_"))
        and (not key.startswith("PIP_") or key in index_options)
    }
    env.update(
        PIPX_HOME=str(root / "pipx"),
        PIPX_BIN_DIR=str(root / "bin"),
        PIPX_MAN_DIR=str(root / "man"),
        PIPX_SHARED_LIBS=str(root / "shared"),
        PIPX_LOG_DIR=str(root / "logs"),
        PIPX_DEFAULT_BACKEND="pip",
        PIP_CONFIG_FILE=os.devnull,
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PIP_NO_INPUT="1",
        PATH=str(root / "bin") + os.pathsep + env.get("PATH", ""),
    )
    return env


def run(
    args: list[str], *, cwd: Path, env: dict[str, str], timeout: int | None = 300
) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True, timeout=timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, help="Lokalny plik .whl do sprawdzenia.")
    parser.add_argument(
        "--python", default=sys.executable, help="Interpreter instalacji."
    )
    parser.add_argument(
        "--gui", action="store_true", help="Wymagaj GUI i zainstaluj dodatek gui."
    )
    parser.add_argument(
        "--inspect-only", action="store_true", help="Sprawdź samo archiwum."
    )
    parser.add_argument(
        "--interactive", action="store_true", help="Po smoke uruchom TUI; q kończy."
    )
    args = parser.parse_args()
    if args.interactive and (args.inspect_only or not sys.stdin.isatty()):
        parser.error("--interactive wymaga terminala i weryfikacji instalacji.")
    wheel = args.wheel.expanduser().resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error("Podaj istniejący plik wheel.")
    try:
        has_gui = inspect_wheel(wheel, require_gui=args.gui)
    except (
        OSError,
        ValueError,
        KeyError,
        zipfile.BadZipFile,
        configparser.Error,
    ) as error:
        parser.error(f"Nieprawidłowy wheel: {error}")
    if not args.inspect_only:
        uv = shutil.which("uv")
        if uv is None:
            parser.error("Brak uv na PATH.")
        python_path = Path(args.python).expanduser()
        interpreter = (
            str(python_path.absolute()) if python_path.is_file() else args.python
        )
        smoke = Path(__file__).with_name("smoke_installed.py").resolve()
        with TemporaryDirectory(prefix="portscanner-release-") as temporary:
            root = Path(temporary)
            env = isolated_environment(root)
            spec = str(wheel) + ("[gui]" if args.gui else "")
            run(
                [
                    uv,
                    "tool",
                    "run",
                    "--from",
                    "pipx==1.17.2",
                    "pipx",
                    "install",
                    "--backend",
                    "pip",
                    "--python",
                    interpreter,
                    spec,
                ],
                cwd=root,
                env=env,
            )
            windows = os.name == "nt"
            venv = root / "pipx/venvs/portscanner"
            python = venv / ("Scripts/python.exe" if windows else "bin/python")
            command = root / "bin" / ("portscanner.exe" if windows else "portscanner")
            run([str(python), "-m", "pip", "check"], cwd=root, env=env)
            run(
                [
                    str(python),
                    "-I",
                    str(smoke),
                    str(command),
                    *(["--gui"] if args.gui else []),
                ],
                cwd=root,
                env=env,
            )
            if args.interactive:
                run([str(command)], cwd=root, env=env, timeout=None)
    with wheel.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    scope = "archiwum" if args.inspect_only else "archiwum i instalacja"
    print(f"OK: {scope} — {platform.system()} {platform.machine()} — {wheel.name}")
    print(f"Zasoby GUI: {'tak' if has_gui else 'nie'}")
    print(f"SHA256: {digest}")


if __name__ == "__main__":
    main()
