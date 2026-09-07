"""Model zachowuje dane gniazda mimo niepełnej widoczności procesów."""

import json
from dataclasses import asdict

from portscanner.core.model import PortEntry


def test_socket_without_visible_process_can_be_serialized() -> None:
    entry = PortEntry(proto="tcp", bind="::", port=5432)

    assert json.loads(json.dumps(asdict(entry))) == {
        "proto": "tcp",
        "bind": "::",
        "port": 5432,
        "pid": None,
    }
