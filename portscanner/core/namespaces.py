"""Wspólna kontrola przestrzeni nazw; błąd odczytu nie potwierdza zgodności."""

import sys
from pathlib import Path


def same_namespaces(pid: int) -> bool:
    if sys.platform != "linux":
        return True
    return all(
        Path(f"/proc/{pid}/ns/{kind}").stat().st_ino
        == Path(f"/proc/self/ns/{kind}").stat().st_ino
        for kind in ("net", "mnt")
    )
