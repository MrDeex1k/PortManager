"""Lekki bundle macOS wskazuje dokładnie wejście CLI GUI."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from portscanner.gui.macos_app import _publish_bundle, build_app


@pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS bundle publication")
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX execute permission bits")
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


@pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS bundle publication")
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


@pytest.mark.parametrize("existing_target", [False, True])
def test_build_app_rejects_output_symlink(tmp_path, existing_target):
    command = tmp_path / "command"
    command.write_text("#!/bin/sh\n")
    command.chmod(0o755)
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"icon")
    target = tmp_path / "elsewhere.app"
    if existing_target:
        target.mkdir()
    output = tmp_path / "requested.app"
    try:
        output.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Tworzenie dowiązań wymaga dodatkowych uprawnień")
    with pytest.raises(ValueError, match="już istnieje"):
        build_app(command, output, icon=icon)
    assert output.is_symlink()
    assert target.exists() == existing_target


@pytest.mark.skipif(os.name != "posix", reason="POSIX shell launcher")
def test_launcher_finds_sibling_tools_with_finder_path(tmp_path, monkeypatch):
    import shlex

    from portscanner.gui import macos_app

    directory = tmp_path / "bin with ' quote"
    directory.mkdir()
    helper = directory / "portmanager-test-tool"
    helper.write_text("#!/bin/sh\n")
    helper.chmod(0o755)
    result = tmp_path / "result"
    command = directory / "portscanner"
    command.write_text(
        f"#!/bin/sh\ncommand -v portmanager-test-tool > {shlex.quote(str(result))}\n"
    )
    command.chmod(0o755)
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"icon")
    monkeypatch.setattr(
        macos_app, "_publish_bundle", lambda bundle, output: bundle.rename(output)
    )
    app = build_app(command, tmp_path / "PortManager.app", icon=icon)
    subprocess.run(
        [app / "Contents/MacOS/PortManager"], env={"PATH": "/usr/bin:/bin"}, check=True
    )
    assert result.read_text().strip() == str(helper)
