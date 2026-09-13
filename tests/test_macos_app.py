"""Lekki bundle macOS wskazuje dokładnie wejście CLI GUI."""

import os
import plistlib
import subprocess
from pathlib import Path

import pytest

from portscanner.gui.macos_app import build_app


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
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"icon")
    output = tmp_path / "PortManager.app"
    output.mkdir()
    with pytest.raises(ValueError, match="już istnieje"):
        build_app(command, output, icon=icon)
