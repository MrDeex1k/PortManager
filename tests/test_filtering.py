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
    rows = entries()
    try:
        matched = filter_entries(rows, case["query"].strip() or None)
    except ValueError:
        assert not case["ids"]
    else:
        assert [str(rows.index(row)) for row in matched] == case["ids"]
