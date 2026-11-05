"""Drift between Python models, bridge responses and TypeScript fails tests."""

import subprocess
import sys
from pathlib import Path


def test_generated_wire_contracts_are_current():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "scripts/generate_contracts.py", "--check"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
