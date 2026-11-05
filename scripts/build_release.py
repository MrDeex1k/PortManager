"""Build an isolated CLI/TUI or fresh GUI release without reusing local assets."""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, timeout=900)


def publish(source: Path, destination: Path) -> None:
    """Do not truncate an earlier artifact when copying fails."""
    temporary = None
    try:
        with NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with source.open("rb") as incoming:
                shutil.copyfileobj(incoming, stream)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_release(output: Path, *, gui: bool = False) -> list[Path]:
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("Brak uv na PATH.")
    bun = shutil.which("bun")
    if gui and (not bun or not shutil.which("node")):
        raise ValueError("Build GUI wymaga Bun i Node na PATH.")
    with TemporaryDirectory(prefix="portmanager-build-") as directory:
        root = Path(directory)
        source_dist = root / "source"
        run(
            [uv, "build", "--sdist", "--out-dir", str(source_dist), str(ROOT)], cwd=root
        )
        archives = list(source_dist.glob("*.tar.gz"))
        if len(archives) != 1:
            raise ValueError("Build nie utworzył dokładnie jednego sdist.")
        source = root / "unpacked"
        with tarfile.open(archives[0]) as archive:
            archive.extractall(source, filter="data")
        projects = list(source.iterdir())
        if len(projects) != 1 or not (projects[0] / "pyproject.toml").is_file():
            raise ValueError("Nieprawidłowa struktura sdist.")
        project = projects[0]
        # The initial sdist may contain ignored assets from a developer's build.
        # They must never determine whether this release contains a GUI.
        assets = project / "portscanner/gui/assets"
        if assets.exists():
            shutil.rmtree(assets)
        if gui and bun is not None:
            run([bun, "install", "--frozen-lockfile"], cwd=project / "frontend")
            run([bun, "run", "build"], cwd=project / "frontend")
        built = root / "built"
        run([uv, "build", "--out-dir", str(built), str(project)], cwd=root)
        wheels = list(built.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("Build nie utworzył dokładnie jednego wheel.")
        run(
            [
                sys.executable,
                "-I",
                str(ROOT / "scripts/verify_release.py"),
                str(wheels[0]),
                "--inspect-only",
                *(["--gui"] if gui else []),
            ],
            cwd=root,
        )
        output.mkdir(parents=True, exist_ok=True)
        artifacts = sorted([*wheels, *built.glob("*.tar.gz")])
        for artifact in artifacts:
            publish(artifact, output / artifact.name)
        return [output / artifact.name for artifact in artifacts]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gui", action="store_true", help="Przebuduj i dołącz frontend."
    )
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        for artifact in build_release(args.output.expanduser().resolve(), gui=args.gui):
            print(artifact)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Build wydania nie powiódł się: {error}\n")


if __name__ == "__main__":
    main()
