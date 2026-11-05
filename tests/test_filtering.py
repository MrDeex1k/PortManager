import json
from pathlib import Path

import pytest

from portscanner.core.filtering import filter_entries
from portscanner.core.model import (
    DockerPort,
    KubernetesPort,
    PortEntry,
    ProcessInfo,
    TunnelRoute,
)

DATA = json.loads((Path(__file__).parent / "fixtures/filter_cases.json").read_text())


def entries():
    """Convert the shared JSON fixture into immutable core models for parity checks."""
    result = []
    for raw in DATA["ports"]:
        data = {key: value for key, value in raw.items() if key != "id"}
        process = data["process"]
        if process:
            data["process"] = ProcessInfo(
                process["pid"],
                process["status"],
                process["name"],
                tuple(process["cmdline"]) if process["cmdline"] is not None else None,
            )
        for field, cls in (
            ("docker", DockerPort),
            ("kubernetes", KubernetesPort),
            ("tunnels", TunnelRoute),
        ):
            data[field] = tuple(cls(**item) for item in data[field])
        data["tags"] = ()
        result.append(PortEntry(**data))
    return result


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda case: case["query"])
def test_shared_filter_contract(case):
    """Require errors only for invalid queries and exact matches for valid queries."""
    rows = entries()
    query = case["query"].strip() or None
    if case.get("invalid", False):
        with pytest.raises(ValueError):
            filter_entries(rows, query)
    else:
        matched = filter_entries(rows, query)
        assert [str(rows.index(row)) for row in matched] == case["ids"]
