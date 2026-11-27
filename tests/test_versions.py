"""Versions come from bounded declarations tied to the process, never port guesses."""

import json
import os
import plistlib
from pathlib import Path
from unittest.mock import Mock

import psutil
import pytest

from portscanner.core.model import ApplicationVersion
from portscanner.core.versions import (
    MAX_PACKAGE_PARENTS,
    METADATA_LIMIT,
    read_application_version,
)


def node_process(project: Path) -> Mock:
    process = Mock()
    process.exe.return_value = "/usr/bin/node"
    process.cwd.return_value = str(project)
    return process


def make_project(project: Path, metadata: object = None) -> Path:
    project.mkdir(parents=True, exist_ok=True)
    script = project / "server.js"
    script.touch()
    (project / "package.json").write_text(
        json.dumps(
            metadata if metadata is not None else {"name": "demo", "version": "1.2.3"}
        )
    )
    return script


@pytest.mark.parametrize("runtime", ["node", "/usr/local/bin/node", "bun", "node.exe"])
def test_explicit_script_relative_to_process_cwd(tmp_path: Path, runtime: str) -> None:
    make_project(tmp_path)
    process = node_process(tmp_path)
    assert read_application_version(
        process, (runtime, "server.js")
    ) == ApplicationVersion("1.2.3", "package_json", "demo")


def test_absolute_bun_run_script_does_not_need_cwd(tmp_path: Path) -> None:
    script = make_project(tmp_path)
    process = node_process(tmp_path)
    assert read_application_version(process, ("bun", "run", str(script)))
    process.cwd.assert_not_called()


@pytest.mark.parametrize(
    "cmdline",
    [
        ("python", "server.js"),
        ("node",),
        ("node", "-e", "server.js"),
        ("node", "--require", "server.js"),
        ("bun", "run", "start"),
        ("node", "missing.js"),
    ],
)
def test_unrelated_cwd_never_supplies_version(
    tmp_path: Path, cmdline: tuple[str, ...]
) -> None:
    make_project(tmp_path)
    assert read_application_version(node_process(tmp_path), cmdline) is None


@pytest.mark.parametrize(
    "metadata", [{}, {"version": 12}, [], {"version": "a\nsecret"}]
)
def test_nearest_unversioned_package_blocks_parent_fallback(
    tmp_path: Path, metadata: object
) -> None:
    make_project(tmp_path)
    script = make_project(tmp_path / "child", metadata)
    assert (
        read_application_version(node_process(tmp_path), ("node", str(script))) is None
    )


@pytest.mark.parametrize("content", ["{invalid", "x" * (METADATA_LIMIT + 1)])
def test_malformed_and_oversized_metadata_is_unknown(
    tmp_path: Path, content: str
) -> None:
    script = make_project(tmp_path)
    (tmp_path / "package.json").write_text(content)
    assert (
        read_application_version(node_process(tmp_path), ("node", str(script))) is None
    )


def test_search_has_parent_limit(tmp_path: Path) -> None:
    make_project(tmp_path)
    nested = tmp_path.joinpath(*["child"] * MAX_PACKAGE_PARENTS)
    nested.mkdir(parents=True)
    script = nested / "server.js"
    script.touch()
    assert (
        read_application_version(node_process(tmp_path), ("node", str(script))) is None
    )


def test_manifest_symlink_is_not_read(tmp_path: Path) -> None:
    script = make_project(tmp_path)
    manifest = tmp_path / "package.json"
    manifest.rename(tmp_path / "metadata.json")
    manifest.symlink_to(tmp_path / "metadata.json")
    assert (
        read_application_version(node_process(tmp_path), ("node", str(script))) is None
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_manifest_fifo_is_not_read(tmp_path: Path) -> None:
    script = make_project(tmp_path)
    manifest = tmp_path / "package.json"
    manifest.unlink()
    os.mkfifo(manifest)
    assert (
        read_application_version(node_process(tmp_path), ("node", str(script))) is None
    )


@pytest.mark.parametrize("binary", [False, True])
def test_macos_bundle_version(tmp_path: Path, binary: bool) -> None:
    contents = tmp_path / "Demo.app" / "Contents"
    contents.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {"CFBundleShortVersionString": "4.2", "CFBundleName": "Demo"},
            fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML,
        )
    )
    process = node_process(tmp_path)
    process.exe.return_value = str(contents / "MacOS" / "Demo")
    assert read_application_version(process, ()) == ApplicationVersion(
        "4.2", "macos_bundle", "Demo"
    )


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"<?xml version='1.0'?><plist><broken>", id="invalid-xml"),
        pytest.param(
            b"<?xml version='1.0'?><plist><key>x</key></plist>",
            id="key-outside-dict",
        ),
    ],
)
def test_malformed_plist_does_not_fail_collection(
    tmp_path: Path, content: bytes
) -> None:
    contents = tmp_path / "Demo.app" / "Contents"
    contents.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(content)
    process = node_process(tmp_path)
    process.exe.return_value = str(contents / "MacOS" / "Demo")
    assert read_application_version(process, ()) is None


def test_denied_metadata_is_unknown(tmp_path: Path) -> None:
    make_project(tmp_path)
    process = node_process(tmp_path)
    process.exe.side_effect = psutil.AccessDenied(42)
    process.cwd.side_effect = psutil.AccessDenied(42)
    assert read_application_version(process, ("node", "server.js")) is None


def test_disappeared_process_propagates(tmp_path: Path) -> None:
    process = node_process(tmp_path)
    process.exe.side_effect = psutil.NoSuchProcess(42)
    with pytest.raises(psutil.NoSuchProcess):
        read_application_version(process, ())


def test_explicit_script_precedes_embedded_runtime_bundle(tmp_path: Path) -> None:
    project = tmp_path / "project"
    make_project(project)
    bundle = tmp_path / "Runtime.app" / "Contents"
    bundle.mkdir(parents=True)
    (bundle / "Info.plist").write_bytes(plistlib.dumps({"CFBundleVersion": "99.0"}))
    process = node_process(project)
    process.exe.return_value = str(bundle / "MacOS" / "node")
    assert read_application_version(
        process, ("node", "server.js")
    ) == ApplicationVersion("1.2.3", "package_json", "demo")
    (project / "package.json").unlink()
    assert read_application_version(process, ("node", "server.js")) is None
