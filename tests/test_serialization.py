"""Streaming exports preserve existing bytes and retain snapshot diagnostics."""

import io
import json
from dataclasses import asdict

import pytest

from portscanner.core.model import (
    PortEntry,
    ProcessInfo,
    Snapshot,
    SourceReport,
    TunnelInfo,
)
from portscanner.serialization import write_ports_json, write_snapshot_json


@pytest.mark.parametrize("count", [0, 1, 3])
def test_list_bytes_match_existing_contract(count):
    """Unicode, argument boundaries and null values retain the original encoding."""
    entries = tuple(
        PortEntry(
            "tcp",
            "::1",
            80 + i,
            process=ProcessInfo(None, "ok", "żółć", ("a\nb", 'c"d')),
        )
        for i in range(count)
    )
    stream = io.StringIO()
    write_ports_json(entries, stream)
    assert (
        stream.getvalue()
        == json.dumps([asdict(entry) for entry in entries], ensure_ascii=True, indent=2)
        + "\n"
    )


def test_first_record_is_written_before_consuming_next():
    """Export must not materialize the entire input before writing to the stream."""
    stream = io.StringIO()

    def entries():
        yield PortEntry("tcp", "127.0.0.1", 80)
        assert '"port": 80' in stream.getvalue()
        yield PortEntry("tcp", "127.0.0.1", 81)

    write_ports_json(entries(), stream)
    assert [row["port"] for row in json.loads(stream.getvalue())] == [80, 81]


def test_snapshot_bytes_match_dataclass_schema():
    """Full export includes all model arrays without collapsing diagnostic fields."""
    snapshot = Snapshot(
        (PortEntry("tcp", "127.0.0.1", 80),),
        (),
        (),
        (TunnelInfo(42, config_code="unsafe_file", metrics_code="timeout"),),
        (SourceReport("listeners", "partial", code="udp_peer_unknown"),),
    )
    stream = io.StringIO()
    write_snapshot_json(snapshot, snapshot.ports, stream)
    assert (
        stream.getvalue()
        == json.dumps(asdict(snapshot), ensure_ascii=True, indent=2) + "\n"
    )
