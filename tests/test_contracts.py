"""Drift between Python models, bridge responses and TypeScript fails tests."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_generated_wire_contracts_are_current():
    """Compare generated contracts when the optional frontend toolchain is installed."""
    root = Path(__file__).resolve().parents[1]
    if shutil.which("bun") is None or not (root / "frontend/node_modules").is_dir():
        pytest.skip("Wymaga Bun i zależności frontendu (bun install --frozen-lockfile)")
    result = subprocess.run(
        [sys.executable, "scripts/generate_contracts.py", "--check"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
