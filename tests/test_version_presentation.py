import json
from io import StringIO

from portscanner.core.filtering import filter_entries
from portscanner.core.model import (
    ApplicationVersion,
    DockerPort,
    PortEntry,
    ProcessInfo,
)
from portscanner.presentation import COLUMNS, entry_cells
from portscanner.serialization import write_ports_json


def versioned_entry():
    return PortEntry(
        "tcp",
        "127.0.0.1",
        8080,
        pid=42,
        process=ProcessInfo(
            42,
            "ok",
            "node",
            application_version=ApplicationVersion("1.2.3", "package_json", "web-app"),
        ),
        docker=(
            DockerPort(
                "abc",
                "backend",
                "127.0.0.1",
                8080,
                80,
                "tcp",
                application_version=ApplicationVersion("4.5.6", "oci_label"),
                image="backend:stable",
            ),
        ),
    )


def test_versions_preserve_ownership_and_source_in_terminal_and_json():
    row = versioned_entry()
    cell = entry_cells(row)[COLUMNS.index("VERSION")]
    assert "1.2.3 [package_json]" in cell
    assert "backend: 4.5.6 [oci_label]" in cell
    stream = StringIO()
    write_ports_json([row], stream)
    data = json.loads(stream.getvalue())[0]
    assert data["process"]["application_version"]["application"] == "web-app"
    assert data["docker"][0]["application_version"]["source"] == "oci_label"
    assert data["docker"][0]["image"] == "backend:stable"


def test_version_metadata_is_searchable_and_missing_version_stays_unknown():
    row = versioned_entry()
    for query in ("1.2.3", "4.5.6", "WEB-APP", "backend:stable", "oci_label"):
        assert filter_entries([row], query) == [row]
    unknown = PortEntry("tcp", "*", 3000)
    assert entry_cells(unknown)[COLUMNS.index("VERSION")] == "—"
