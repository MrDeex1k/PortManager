"""Release archive checks and installed CLI smoke use explicit contracts."""

import json
import os
import subprocess
import zipfile
from unittest.mock import Mock

import pytest

from scripts import build_gui_icon, build_release, smoke_installed, verify_release


def make_wheel(path, *, gui=False, links=None, missing=(), name="portscanner"):
    prefix = "portscanner-0.1.0.dist-info/"
    files = {
        prefix + "METADATA": f"Name: {name}\nVersion: 0.1.0\n",
        prefix
        + "entry_points.txt": "[console_scripts]\nportscanner=portscanner.cli:main\n"
        "portscanner-macos-app=portscanner.gui.macos_app:main\n",
        "portscanner/__init__.py": "",
        "portscanner/cli.py": "",
        "portscanner/tui/app.py": "",
        "portscanner/gui/macos_app.py": "",
        "portscanner/gui/icons/portmanager.icns": "icon",
    }
    if gui:
        files.update(
            {
                "portscanner/gui/assets/index.html": links
                or (
                    '<script type="module" src="./assets/app.js"></script>'
                    '<link rel="stylesheet" href="./assets/app.css">'
                ),
                "portscanner/gui/assets/assets/app.js": "code",
                "portscanner/gui/assets/assets/app.css": "style",
                "portscanner/gui/assets/icons/portmanager-128.png": "icon",
            }
        )
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            if name not in missing:
                archive.writestr(name, content)
    return path


def test_wheel_inspection_distinguishes_core_and_gui(tmp_path):
    wheel = make_wheel(tmp_path / "core.whl")
    assert verify_release.inspect_wheel(wheel) is False
    with pytest.raises(ValueError, match="nie zawiera GUI"):
        verify_release.inspect_wheel(wheel, require_gui=True)
    make_wheel(wheel, gui=True)
    assert verify_release.inspect_wheel(wheel, require_gui=True)


@pytest.mark.parametrize(
    "url",
    [
        "./assets/missing.js",
        "https://example.com/app.js",
        "../cli.py",
        "/assets/app.js",
        "%2e%2e/cli.py",
    ],
)
def test_gui_rejects_missing_or_nonlocal_assets(tmp_path, url):
    wheel = make_wheel(
        tmp_path / "gui.whl",
        gui=True,
        links=f'<script type="module" src="{url}"></script>',
    )
    with pytest.raises(ValueError, match="zasobu GUI"):
        verify_release.inspect_wheel(wheel, require_gui=True)


@pytest.mark.parametrize(
    "missing",
    [
        "portscanner/gui/assets/index.html",
        "portscanner/gui/assets/icons/portmanager-128.png",
        "portscanner/cli.py",
    ],
)
def test_incomplete_wheel_is_rejected(tmp_path, missing):
    wheel = make_wheel(tmp_path / "broken.whl", gui=True, missing=[missing])
    with pytest.raises(ValueError):
        verify_release.inspect_wheel(wheel)


def test_other_project_is_rejected_before_installation(tmp_path):
    wheel = make_wheel(tmp_path / "other.whl", name="other")
    with pytest.raises(ValueError, match="nie jest wydaniem"):
        verify_release.inspect_wheel(wheel)


@pytest.mark.parametrize(
    "status,code,exit_code",
    [
        ("ok", None, 0),
        ("partial", "udp_peer_unknown", 0),
        ("partial", "permission_denied", 1),
        ("error", "unavailable", 1),
    ],
)
def test_installed_cli_smoke_accepts_partial_reads(status, code, exit_code):
    report = {"source": "listeners", "status": status, "code": code}
    result = subprocess.CompletedProcess(
        [],
        exit_code,
        json.dumps({"ports": [], "reports": [report]}),
        f"listeners: {status}",
    )
    smoke_installed.check_cli_result(result)
    result.returncode = 1 - exit_code
    with pytest.raises(RuntimeError, match="Kod wyjścia"):
        smoke_installed.check_cli_result(result)


def test_pipx_verification_does_not_inherit_install_destinations(tmp_path, monkeypatch):
    for key in ("PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIPX_HOME", "PYTHONPATH"):
        monkeypatch.setenv(key, "outside")
    monkeypatch.setenv("PIP_CONFIG_FILE", "outside/pip.conf")
    monkeypatch.setenv("PIP_INDEX_URL", "https://mirror.example/simple")
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(tmp_path / "wheels"))
    env = verify_release.isolated_environment(tmp_path)
    assert not {"PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PYTHONPATH"} & env.keys()
    assert env["PIPX_HOME"] == str(tmp_path / "pipx")
    assert env["PIP_CONFIG_FILE"] == os.devnull
    assert env["PIP_INDEX_URL"] == "https://mirror.example/simple"
    assert env["PIP_NO_INDEX"] == "1"
    assert env["PIP_FIND_LINKS"] == str(tmp_path / "wheels")


def test_inspect_only_does_not_install_anything(tmp_path, monkeypatch, capsys):
    wheel = make_wheel(tmp_path / "portscanner.whl", gui=True)
    run = Mock(side_effect=AssertionError("must not install"))
    monkeypatch.setattr(verify_release, "run", run)
    monkeypatch.setattr("sys.argv", ["verify", str(wheel), "--inspect-only", "--gui"])
    verify_release.main()
    assert "SHA256:" in capsys.readouterr().out
    run.assert_not_called()


def test_failed_artifact_copy_keeps_previous_release(tmp_path, monkeypatch):
    source = tmp_path / "new.whl"
    source.write_bytes(b"new")
    output = tmp_path / "release.whl"
    output.write_bytes(b"old")

    def fail(incoming, outgoing):
        outgoing.write(b"partial")
        raise OSError("disk")

    monkeypatch.setattr(build_release.shutil, "copyfileobj", fail)
    with pytest.raises(OSError):
        build_release.publish(source, output)
    assert output.read_bytes() == b"old"
    assert set(tmp_path.iterdir()) == {source, output}


def test_failed_icon_build_keeps_previous_icon(tmp_path, monkeypatch):
    icon = tmp_path / "portmanager.icns"
    icon.write_bytes(b"old")
    monkeypatch.setattr(build_gui_icon, "OUTPUT", icon)

    def run(args, **kwargs):
        assert kwargs["timeout"] == 30
        if args[0] == "iconutil":
            from pathlib import Path

            Path(args[-1]).write_bytes(b"partial")
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(build_gui_icon.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        build_gui_icon.main()
    assert icon.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [icon]


@pytest.mark.parametrize("gui", [False, True])
def test_release_build_uses_clean_source_and_fresh_gui(tmp_path, monkeypatch, gui):
    import tarfile
    from pathlib import Path

    original = tmp_path / "repo"
    original.mkdir()
    (original / "pyproject.toml").write_text("[project]\nname='portscanner'\n")
    (original / "frontend").mkdir()
    stale = original / "portscanner/gui/assets/index.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("STALE")
    monkeypatch.setattr(build_release, "ROOT", original)
    monkeypatch.setattr(build_release.shutil, "which", lambda name: "/tools/" + name)
    steps = []

    def run(args, *, cwd):
        steps.append(args)
        if args[0] == "/tools/bun":
            assert not (cwd.parent / "portscanner/gui/assets").exists()
            if args[1] == "run":
                entry = cwd.parent / "portscanner/gui/assets/index.html"
                entry.parent.mkdir(parents=True)
                entry.write_text("FRESH")
            return
        if args[0] != "/tools/uv":
            wheel = Path(args[3])
            assert verify_release.inspect_wheel(wheel, require_gui=gui) == gui
            return
        output = Path(args[args.index("--out-dir") + 1])
        output.mkdir()
        project = Path(args[-1])
        if "--sdist" not in args:
            entry = project / "portscanner/gui/assets/index.html"
            assert entry.exists() == gui
            if gui:
                assert entry.read_text() == "FRESH"
            make_wheel(output / "portscanner.whl", gui=gui)
        with tarfile.open(output / "portscanner.tar.gz", "w:gz") as archive:
            archive.add(project, arcname="portscanner")

    monkeypatch.setattr(build_release, "run", run)
    output = tmp_path / "dist"
    artifacts = build_release.build_release(output, gui=gui)
    assert len(artifacts) == 2 and all(path.is_file() for path in artifacts)
    assert stale.read_text() == "STALE"
    assert sum(step[0] == "/tools/bun" for step in steps) == (2 if gui else 0)
