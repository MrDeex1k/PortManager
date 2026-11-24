"""Passive, bounded metadata discovery; never execute a process or probe its port."""

import json
import os
import plistlib
import stat
from pathlib import Path
from xml.parsers.expat import ExpatError

import psutil

from portscanner.core.model import ApplicationVersion

METADATA_LIMIT = 256 * 1024
MAX_PACKAGE_PARENTS = 8
_SCRIPT_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}


def metadata_text(value: object) -> str | None:
    """Only short printable declarations are suitable for version/name metadata."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 200 or not value.isprintable():
        return None
    return value


def _read_metadata(path: Path) -> bytes:
    # Nonblocking prevents a substituted FIFO from blocking collection. Reject
    # symlinks and nonregular files, then cap the read even if the file grows.
    if path.is_symlink():
        raise ValueError("Metadata symlinks are not followed")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > METADATA_LIMIT:
            raise ValueError("Metadata is not a bounded regular file")
        data = stream.read(METADATA_LIMIT + 1)
    if len(data) > METADATA_LIMIT:
        raise ValueError("Metadata is too large")
    return data


def _bundle_version(executable: str) -> ApplicationVersion | None:
    path = Path(executable)
    for bundle in path.parents:
        if bundle.suffix != ".app":
            continue
        if not path.is_relative_to(bundle / "Contents"):
            continue
        data = plistlib.loads(_read_metadata(bundle / "Contents" / "Info.plist"))
        if not isinstance(data, dict):
            return None
        version = metadata_text(
            data.get("CFBundleShortVersionString")
        ) or metadata_text(data.get("CFBundleVersion"))
        if version:
            name = metadata_text(data.get("CFBundleDisplayName")) or metadata_text(
                data.get("CFBundleName")
            )
            return ApplicationVersion(version, "macos_bundle", name)
        return None
    return None


def _script_argument(cmdline: tuple[str, ...]) -> str | None:
    if len(cmdline) < 2:
        return None
    runtime = Path(cmdline[0]).name.lower().removesuffix(".exe")
    if runtime not in {"node", "nodejs", "bun"}:
        return None
    arguments = list(cmdline[1:])
    if runtime == "bun" and arguments[0] == "run":
        arguments.pop(0)
    if arguments and arguments[0] == "--":
        arguments.pop(0)
    # Conservatively skip flags (including eval/print), package scripts and
    # option-value pairs rather than guessing which argument names a program.
    if not arguments or arguments[0].startswith("-"):
        return None
    candidate = arguments[0]
    return candidate if Path(candidate).suffix in _SCRIPT_SUFFIXES else None


def _package_version(script: Path) -> ApplicationVersion | None:
    try:
        script = script.resolve(strict=True)
    except RuntimeError:
        # Python 3.12 reports a symlink loop as RuntimeError.
        return None
    if not script.is_file():
        return None
    for directory in list(script.parents)[:MAX_PACKAGE_PARENTS]:
        manifest = directory / "package.json"
        try:
            data = json.loads(_read_metadata(manifest))
        except FileNotFoundError:
            continue
        # The closest package owns this script. Do not fall back to an unrelated
        # parent if its metadata is missing, invalid or unversioned.
        if not isinstance(data, dict):
            return None
        version = metadata_text(data.get("version"))
        return (
            ApplicationVersion(version, "package_json", metadata_text(data.get("name")))
            if version
            else None
        )
    return None


def read_application_version(
    process: psutil.Process, cmdline: tuple[str, ...] | None
) -> ApplicationVersion | None:
    """Best effort metadata; inaccessible files must not hide basic process data.

    A disappeared process propagates to the caller, which discards its snapshot.
    Metadata describes files at collection time, not necessarily the loaded build.
    """
    if cmdline and (script_argument := _script_argument(cmdline)):
        try:
            script = Path(script_argument)
            if not script.is_absolute():
                cwd = process.cwd()
                if not isinstance(cwd, str) or not Path(cwd).is_absolute():
                    return None
                script = Path(cwd) / script
            return _package_version(script)
        except psutil.NoSuchProcess:
            raise
        except (
            psutil.Error,
            OSError,
            ValueError,
            TypeError,
            AttributeError,
            RecursionError,
        ):
            return None
    try:
        executable = process.exe()
        if isinstance(executable, str) and executable:
            version = _bundle_version(executable)
            if version is not None:
                return version
    except psutil.NoSuchProcess:
        raise
    except (
        psutil.Error,
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        ExpatError,
        RecursionError,
    ):
        pass
    return None
