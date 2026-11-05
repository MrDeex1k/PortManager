"""Stream snapshot arrays one record at a time without copying the entire model."""

import json
from collections.abc import Iterable
from dataclasses import asdict
from typing import TextIO

from portscanner.core.model import (
    DockerPort,
    LocalIP,
    PortEntry,
    Snapshot,
    SourceReport,
    TunnelInfo,
)

type Record = PortEntry | LocalIP | DockerPort | TunnelInfo | SourceReport


def _write_array(records: Iterable[Record], stream: TextIO, *, level: int = 0) -> None:
    """Preserve pretty JSON formatting while buffering at most one record."""
    stream.write("[")
    first = True
    prefix = "  " * (level + 1)
    for record in records:
        stream.write("\n" if first else ",\n")
        first = False
        encoded = json.dumps(asdict(record), ensure_ascii=True, indent=2)
        stream.write(prefix + encoded.replace("\n", "\n" + prefix))
    if not first:
        stream.write("\n" + "  " * level)
    stream.write("]")


def write_ports_json(entries: Iterable[PortEntry], stream: TextIO) -> None:
    """Write the existing CLI/export list contract, including its final newline."""
    _write_array(entries, stream)
    stream.write("\n")


def write_snapshot_json(
    snapshot: Snapshot, entries: Iterable[PortEntry], stream: TextIO
) -> None:
    """Filter only ports; retain full source reports and discovery metadata."""
    arrays: tuple[tuple[str, Iterable[Record]], ...] = (
        ("ports", entries),
        ("local_ips", snapshot.local_ips),
        ("docker", snapshot.docker),
        ("tunnels", snapshot.tunnels),
        ("reports", snapshot.reports),
    )
    stream.write("{\n")
    for index, (name, records) in enumerate(arrays):
        if index:
            stream.write(",\n")
        stream.write(f'  "{name}": ')
        _write_array(records, stream, level=1)
    stream.write("\n}\n")
