import json
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from portscanner.core.procs import read_process
from portscanner.core.redaction import redact_cmdline


@pytest.mark.parametrize(
    "args,expected",
    [
        (("--password", "--token", "secret"), ("--password", "***", "***")),
        (("--password", "--token=secret", "public"), ("--password", "***", "public")),
        (("--token", "--token", "secret"), ("--token", "***", "***")),
        (("--password", "--API_KEY", "secret"), ("--password", "***", "***")),
        (("--password", "--token"), ("--password", "***")),
        (
            ("--token", "secret", "--token", "other"),
            ("--token", "***", "--token", "***"),
        ),
    ],
)
def test_adjacent_flags_and_missing_values(args, expected):
    assert redact_cmdline(args) == expected


def test_adjacent_secret_never_reaches_process_payload(monkeypatch):
    process = Mock()
    process.name.return_value = "python"
    process.cmdline.return_value = [
        "python",
        "--password",
        "--token",
        "SYNTHETIC_SECRET",
    ]
    process.is_running.return_value = True
    monkeypatch.setattr("psutil.Process", lambda pid: process)
    assert "SYNTHETIC_SECRET" not in json.dumps(asdict(read_process(42)))
