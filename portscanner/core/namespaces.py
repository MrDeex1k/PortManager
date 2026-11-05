"""Wspólna kontrola przestrzeni nazw; błąd odczytu nie potwierdza zgodności."""

import sys
from pathlib import Path


def same_namespaces(pid: int) -> bool:
    if sys.platform != "linux":
        return True
    for kind in ("net", "mnt"):
        target = Path(f"/proc/{pid}/ns/{kind}").stat()
        current = Path(f"/proc/self/ns/{kind}").stat()
        if (target.st_dev, target.st_ino) != (current.st_dev, current.st_ino):
            return False
    return True
