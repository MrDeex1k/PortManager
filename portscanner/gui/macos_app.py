"""Lekki bundle .app uruchamiający zainstalowane `portscanner --gui`."""

import argparse
import ctypes
import errno
import os
import plistlib
import shlex
import shutil
import stat
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

_AT_FDCWD = -2
_RENAME_EXCL = 0x00000004


def _publish_bundle(bundle: Path, output: Path) -> None:
    """Opublikuj bundle atomowo, bez zastępowania istniejącego celu."""
    try:
        renameatx_np = ctypes.CDLL(None, use_errno=True).renameatx_np
    except AttributeError as error:
        raise OSError(
            errno.ENOTSUP,
            "System nie obsługuje atomowej publikacji bundle bez nadpisania.",
            output,
        ) from error
    renameatx_np.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameatx_np.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = renameatx_np(
        _AT_FDCWD,
        os.fsencode(bundle),
        _AT_FDCWD,
        os.fsencode(output),
        _RENAME_EXCL,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in (errno.EEXIST, errno.ENOTEMPTY):
        raise ValueError(f"Ścieżka już istnieje: {output}")
    raise OSError(error_number, os.strerror(error_number), output)


def build_app(command: Path, output: Path, *, icon: Path) -> Path:
    command = command.expanduser().resolve()
    # Resolve the parent only: following the final symlink could publish at a
    # different destination or accept a dangling link as an unused output.
    output = output.expanduser().absolute()
    output = output.parent.resolve() / output.name
    icon = icon.expanduser().resolve()
    if not command.is_file() or not os.access(command, os.X_OK):
        raise ValueError(f"Nie znaleziono polecenia: {command}")
    if not icon.is_file():
        raise ValueError(f"Nie znaleziono ikony: {icon}")
    if output.suffix != ".app":
        raise ValueError("Ścieżka wyjściowa musi kończyć się na .app")
    if os.path.lexists(output):
        raise ValueError(f"Ścieżka już istnieje: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{output.stem}-", dir=output.parent) as directory:
        bundle = Path(directory) / output.name
        macos = bundle / "Contents" / "MacOS"
        resources = bundle / "Contents" / "Resources"
        macos.mkdir(parents=True)
        resources.mkdir()
        launcher = macos / "PortManager"
        # Finder does not load shell startup files. Keep its PATH and make the
        # installed command's siblings and standard Homebrew tools discoverable.
        search_path = shlex.quote(f"{command.parent}:/opt/homebrew/bin:/usr/local/bin")
        launcher.write_text(
            f'#!/bin/sh\nPATH={search_path}:"${{PATH:-/usr/bin:/bin:/usr/sbin:/sbin}}"\n'
            f"export PATH\nexec {shlex.quote(str(command))} --gui\n",
            encoding="utf-8",
        )
        launcher.chmod(
            launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        shutil.copy2(icon, resources / "portmanager.icns")
        info = {
            "CFBundleDevelopmentRegion": "pl",
            "CFBundleDisplayName": "PortManager",
            "CFBundleExecutable": "PortManager",
            "CFBundleIconFile": "portmanager.icns",
            "CFBundleIdentifier": "dev.portmanager.desktop",
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundleName": "PortManager",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": version("portscanner"),
            "CFBundleVersion": version("portscanner"),
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
        }
        with (bundle / "Contents" / "Info.plist").open("wb") as file:
            plistlib.dump(info, file, sort_keys=True)
        _publish_bundle(bundle, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--command",
        type=Path,
        required=True,
        help="Ścieżka do polecenia portscanner z dodatkiem gui.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--icon",
        type=Path,
        default=Path(__file__).with_name("icons") / "portmanager.icns",
    )
    args = parser.parse_args()
    try:
        result = build_app(args.command, args.output, icon=args.icon)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(result)


if __name__ == "__main__":
    main()
