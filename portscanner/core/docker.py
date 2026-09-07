"""Odczyt publikowanych portów przez lokalny Docker CLI, bez zmian daemona."""

import json
import math
import os
import re
import subprocess
from ipaddress import ip_address

from portscanner.core.model import Collection, DockerPort, SourceReport

# Projekcja pomija Env, tokeny, mounty i inne niepotrzebne szczegóły inspect.
_INSPECT_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},'
    '"running":{{json .State.Running}},"ports":{{json .NetworkSettings.Ports}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}}}'
)


def _run(args: list[str], timeout: float) -> str:
    env = os.environ.copy()
    # Jawny --host wybrany poniżej ma pierwszeństwo; nie zmieniamy konfiguracji CLI.
    env.pop("DOCKER_CONTEXT", None)
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=True,
        env=env,
    )
    return result.stdout


def _endpoint(timeout: float) -> str:
    context = os.environ.get("DOCKER_CONTEXT")
    if not context and os.environ.get("DOCKER_HOST"):
        return os.environ["DOCKER_HOST"]
    args = ["context", "inspect"]
    if context:
        args.append(context)
    value = json.loads(
        _run([*args, "--format", "{{json .Endpoints.docker.Host}}"], timeout)
    )
    if not isinstance(value, str):
        raise ValueError("Nieprawidłowy endpoint Docker")
    return value


def parse_inspect(output: str) -> tuple[DockerPort, ...]:
    """Parsuj projekcję JSONL inspect, zachowując każde mapowanie osobno."""
    mappings: set[DockerPort] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("running"), bool):
            raise ValueError("Nieprawidłowy rekord Docker")
        if not row["running"]:
            continue
        if not all(
            isinstance(row.get(key), str) and row[key] for key in ("id", "name")
        ):
            raise ValueError("Brak tożsamości kontenera")
        ports = row.get("ports") or {}
        if not isinstance(ports, dict):
            raise ValueError("Nieprawidłowe porty Docker")
        for key, bindings in ports.items():
            container_port, proto = key.split("/")
            if proto not in ("tcp", "udp") or not bindings:
                continue  # EXPOSE bez publikacji i SCTP są poza modelem TCP/UDP.
            if not isinstance(bindings, list):
                raise ValueError("Nieprawidłowe mapowania Docker")
            for binding in bindings:
                host_port = int(binding["HostPort"])
                target_port = int(container_port)
                if not 1 <= host_port <= 65535 or not 1 <= target_port <= 65535:
                    raise ValueError("Port poza zakresem")
                mappings.add(
                    DockerPort(
                        container_id=row["id"],
                        container_name=row["name"].lstrip("/"),
                        host_bind=str(ip_address(binding["HostIp"])),
                        host_port=host_port,
                        container_port=target_port,
                        proto=proto,
                        compose_project=_label(row.get("project")),
                        compose_service=_label(row.get("service")),
                    )
                )
    return tuple(
        sorted(
            mappings,
            key=lambda item: (
                item.host_port,
                item.proto,
                item.host_bind,
                item.container_id,
                item.container_port,
            ),
        )
    )


def _label(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Nieprawidłowa etykieta Compose")
    return value


def collect_docker(*, timeout: float = 3.0) -> Collection[DockerPort]:
    """Lokalny socket unix/npipe; konteksty TCP/SSH pomijamy bez połączenia.

    ps ustala listę kontenerów, inspect daje strukturalne porty i etykiety.
    Timeout obowiązuje każde wywołanie CLI; inspect jest dzielony na paczki 64 ID.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatni i skończony")
    items: list[DockerPort] = []
    try:
        endpoint = _endpoint(timeout)
        if not endpoint.startswith(("unix:///", "npipe:////./pipe/")):
            return Collection(
                (),
                SourceReport(
                    "docker", "unavailable", "Pominięto nielokalny endpoint Docker."
                ),
            )
        prefix = ["--host", endpoint]
        rows = _run([*prefix, "ps", "--no-trunc", "--format", "json"], timeout)
        ids = []
        for line in rows.splitlines():
            if not line.strip():
                continue
            container_id = json.loads(line)["ID"]
            if not isinstance(container_id, str) or not re.fullmatch(
                r"[0-9a-f]{12,64}", container_id
            ):
                raise ValueError("Nieprawidłowy identyfikator Docker")
            ids.append(container_id)
        for offset in range(0, len(ids), 64):
            items.extend(
                parse_inspect(
                    _run(
                        [
                            *prefix,
                            "inspect",
                            "--type",
                            "container",
                            "--format",
                            _INSPECT_FORMAT,
                            *ids[offset : offset + 64],
                        ],
                        timeout,
                    )
                )
            )
    except FileNotFoundError:
        return Collection((), SourceReport("docker", "unavailable", "Brak Docker CLI."))
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError):
        return Collection(
            tuple(items),
            SourceReport(
                "docker",
                "partial" if items else "error",
                "Niepełny odczyt mapowań Docker (daemon, timeout lub dane).",
            ),
        )
    return Collection(tuple(items), SourceReport("docker", "ok"))
