"""Pinned Kubernetes context and reduced CLI payloads."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from portscanner.core import kube_command as command


def test_context_is_pinned_and_projection_omits_large_fields(monkeypatch):
    """Both resource lists use the resolved context and only necessary fields."""
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, b"cluster-A\n"),
            subprocess.CompletedProcess([], 0, b'{"items":[]}'),
        ]
    )
    monkeypatch.setattr(command, "run_command", run)
    data = json.loads(command.run_kubectl("services,nodes", 3))
    assert data == {"context": "cluster-A", "items": []}
    args = run.call_args_list[1].args[0]
    assert args[:5] == ["kubectl", "--context", "cluster-A", "get", "services,nodes"]
    assert "go-template=" in args[args.index("-o") + 1]
    assert "annotations" not in args[args.index("-o") + 1]
    assert 0 < run.call_args_list[1].args[1] < 3


def test_config_change_during_read_discards_output(monkeypatch, tmp_path):
    """Reject a context/config race instead of mislabelling returned node ports."""
    config = tmp_path / "config"
    config.write_text("current-context: A")
    monkeypatch.setenv("KUBECONFIG", str(config))

    def run(args, *unused, **kwargs):
        if "current-context" in args:
            return subprocess.CompletedProcess([], 0, b"A\n")
        config.write_text("current-context: cluster-B")
        return subprocess.CompletedProcess([], 0, b'{"items":[]}')

    monkeypatch.setattr(command, "run_command", run)
    with pytest.raises(command.ConfigChangedError):
        command.run_kubectl("services,nodes", 3)


def test_fingerprint_includes_each_config_file_and_path(monkeypatch, tmp_path):
    """Path switches and edits in any file of a merged kubeconfig invalidate cache."""
    import os

    first, second = tmp_path / "a", tmp_path / "b"
    first.write_text("first")
    second.write_text("second")
    monkeypatch.setenv("KUBECONFIG", os.pathsep.join([str(first), str(second)]))
    original = command.config_fingerprint()
    second.write_text("changed second")
    assert command.config_fingerprint() != original
    original = command.config_fingerprint()
    monkeypatch.setenv("KUBECONFIG", str(first))
    assert command.config_fingerprint() != original


def test_command_failure_never_exposes_stderr(monkeypatch):
    """Only exit status survives a failed kubectl invocation."""
    monkeypatch.setattr(
        command,
        "run_command",
        Mock(return_value=subprocess.CompletedProcess([], 1, b"", b"SYNTHETIC_SECRET")),
    )
    with pytest.raises(subprocess.CalledProcessError) as error:
        command.run_kubectl("services,nodes", 2)
    assert error.value.stderr is None and "SECRET" not in str(error.value)
