"""Sprawdź lokalny wheel przez pipx, poza repo i bez zmiany instalacji użytkownika.

Wymaga uv na PATH. Pobiera pipx i zależności pakietu; nie publikuje wydania.
"""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def run(args: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True, timeout=300)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, help="Lokalny plik .whl do sprawdzenia.")
    parser.add_argument(
        "--python", default=sys.executable, help="Interpreter instalacji."
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Po smoke uruchom prawdziwy TUI; naciśnij q, aby zakończyć.",
    )
    args = parser.parse_args()
    if args.interactive and not sys.stdin.isatty():
        parser.error("--interactive wymaga terminala.")
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error("Podaj istniejący plik wheel.")
    uv = shutil.which("uv")
    if uv is None:
        parser.error("Brak uv na PATH.")
    interpreter = (
        str(Path(args.python).resolve()) if Path(args.python).is_file() else args.python
    )
    smoke = Path(__file__).with_name("smoke_installed.py").resolve()
    with TemporaryDirectory(prefix="portscanner-release-") as temporary:
        root = Path(temporary)
        env = os.environ.copy()
        env.update(
            PIPX_HOME=str(root / "pipx"),
            PIPX_BIN_DIR=str(root / "bin"),
            PIPX_MAN_DIR=str(root / "man"),
            PIPX_SHARED_LIBS=str(root / "shared"),
            PIPX_LOG_DIR=str(root / "logs"),
            PIPX_DEFAULT_BACKEND="pip",
            PIP_DISABLE_PIP_VERSION_CHECK="1",
            PIP_NO_INPUT="1",
            PATH=str(root / "bin") + os.pathsep + env.get("PATH", ""),
        )
        # Izolacja od ustawień wstrzykujących lokalne moduły do Pythona/pip.
        for variable in (
            "PYTHONPATH",
            "PYTHONHOME",
            "PIP_TARGET",
            "PIP_PREFIX",
            "PIP_USER",
        ):
            env.pop(variable, None)
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
                str(wheel),
            ],
            cwd=root,
            env=env,
        )
        windows = os.name == "nt"
        venv = root / "pipx" / "venvs" / "portscanner"
        python = venv / ("Scripts/python.exe" if windows else "bin/python")
        command = root / "bin" / ("portscanner.exe" if windows else "portscanner")
        run([str(python), "-m", "pip", "check"], cwd=root, env=env)
        # -I oraz cwd poza repo wykluczają przypadkowy import źródeł projektu.
        run([str(python), "-I", str(smoke), str(command)], cwd=root, env=env)
        if args.interactive:
            run([str(command)], cwd=root, env=env)
    with wheel.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    print(f"OK: {platform.system()} {platform.machine()} — {wheel.name}")
    print(f"SHA256: {digest}")


if __name__ == "__main__":
    main()
