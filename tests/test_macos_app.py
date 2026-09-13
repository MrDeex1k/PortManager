"""Lekki bundle macOS wskazuje dokładnie wejście CLI GUI."""

import os
import plistlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from portscanner.gui.macos_app import _publish_bundle, build_app


def test_build_app_creates_icon_and_gui_launcher(tmp_path: Path) -> None:
    command = tmp_path / "port scanner"
    arguments = tmp_path / "arguments"
    command.write_text(f"#!/bin/sh\nprintf '%s' \"$*\" > '{arguments}'\n")
    command.chmod(0o755)
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"icon")
    app = build_app(command, tmp_path / "PortManager.app", icon=icon)

    launcher = app / "Contents" / "MacOS" / "PortManager"
    subprocess.run([launcher], check=True)
    assert arguments.read_text() == "--gui"
    assert os.access(launcher, os.X_OK)
    assert (app / "Contents" / "Resources" / "portmanager.icns").read_bytes() == b"icon"
    with (app / "Contents" / "Info.plist").open("rb") as file:
        info = plistlib.load(file)
    assert info["CFBundleExecutable"] == "PortManager"
    assert info["CFBundleIconFile"] == "portmanager.icns"
    assert info["CFBundlePackageType"] == "APPL"


def test_build_app_refuses_overwrite(tmp_path: Path) -> None:
    command = tmp_path / "portscanner"
    command.write_text("#!/bin/sh\n")
    command.chmod(0o755)
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"icon")
    output = tmp_path / "PortManager.app"
    output.mkdir()
    with pytest.raises(ValueError, match="już istnieje"):
        build_app(command, output, icon=icon)


def test_build_app_rejects_non_executable_command(tmp_path: Path) -> None:
    command = tmp_path / "portscanner"
    command.write_text("#!/bin/sh\n")
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"icon")
    output = tmp_path / "PortManager.app"
    with pytest.raises(ValueError, match="Nie znaleziono polecenia"):
        build_app(command, output, icon=icon)
    assert not output.exists()


def test_build_app_cleans_up_failed_temporary_bundle(tmp_path: Path) -> None:
    command = tmp_path / "portscanner"
    command.write_text("#!/bin/sh\n")
    command.chmod(0o755)
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"icon")
    output = tmp_path / "PortManager.app"
    with (
        patch("portscanner.gui.macos_app.shutil.copy2", side_effect=OSError("disk")),
        pytest.raises(OSError, match="disk"),
    ):
        build_app(command, output, icon=icon)
    assert not output.exists()
    assert list(tmp_path.glob(".PortManager-*")) == []


def test_publish_bundle_never_replaces_existing_empty_directory(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "temporary.app"
    marker = bundle / "Contents" / "marker"
    marker.parent.mkdir(parents=True)
    marker.write_text("new")
    output = tmp_path / "PortManager.app"
    output.mkdir()

    with pytest.raises(ValueError, match="już istnieje"):
        _publish_bundle(bundle, output)

    assert output.is_dir() and list(output.iterdir()) == []
    assert marker.read_text() == "new"


def test_publish_bundle_fails_closed_without_macos_api(tmp_path: Path) -> None:
    bundle = tmp_path / "temporary.app"
    bundle.mkdir()
    output = tmp_path / "PortManager.app"
    with (
        patch("portscanner.gui.macos_app.ctypes.CDLL", return_value=object()),
        pytest.raises(OSError, match="atomowej publikacji"),
    ):
        _publish_bundle(bundle, output)
    assert bundle.exists()
    assert not output.exists()
