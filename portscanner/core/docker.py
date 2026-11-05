"""Read local Docker publications with bounded output and partial-result recovery."""

import json
import math
import os
import re
import subprocess
import time
from ipaddress import ip_address

from portscanner.core.command import run_command
from portscanner.core.discovery_errors import error_code
from portscanner.core.model import Collection, DockerPort, SourceReport

_INSPECT_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},'
    '"running":{{json .State.Running}},"ports":{{json .NetworkSettings.Ports}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}}}'
)
OUTPUT_LIMIT = 4 * 1024 * 1024


def _run(args: list[str], timeout: float) -> str:
    """Keep bounded stdout on failure so healthy inspect records remain usable."""
    env = os.environ.copy()
    env.pop("DOCKER_CONTEXT", None)
    result = run_command(["docker", *args], timeout, limit=OUTPUT_LIMIT, env=env)
    output = result.stdout.decode("utf-8")
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, "docker", output=output)
    return output


def _endpoint(timeout: float) -> str:
    """Honor context precedence while leaving the user's Docker config unchanged."""
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


def _port(value: object) -> int:
    """Accept only Docker's ASCII decimal strings, never coerced bools/floats."""
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ValueError("Nieprawidłowy port Docker")
    if len(value) > 5 or not 1 <= int(value) <= 65535:
        raise ValueError("Port poza zakresem")
    return int(value)


def _label(value: object) -> str | None:
    """Validate optional Compose labels without interpreting arbitrary objects."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Nieprawidłowa etykieta Compose")
    return value


def _binding(row: dict, key: str, binding: object) -> DockerPort | None:
    """Skip routed bindings with no host port; validate all remaining fields."""
    container_port, proto = key.split("/")
    target = _port(container_port)
    if not isinstance(binding, dict) or not isinstance(binding.get("HostIp"), str):
        raise ValueError("Nieprawidłowe mapowanie Docker")
    host = str(ip_address(binding["HostIp"]))
    if binding.get("HostPort") == "":
        return None
    return DockerPort(
        row["id"],
        row["name"].lstrip("/"),
        host,
        _port(binding.get("HostPort")),
        target,
        "tcp" if proto == "tcp" else "udp",
        _label(row.get("project")),
        _label(row.get("service")),
    )


def _parse(output: str, *, tolerant: bool) -> tuple[tuple[DockerPort, ...], bool]:
    """Isolate malformed lines and bindings while preserving other publications."""
    mappings: set[DockerPort] = set()
    invalid = False
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or type(row.get("running")) is not bool:
                raise ValueError("Nieprawidłowy rekord Docker")
            if not row["running"]:
                continue
            if not all(isinstance(row.get(k), str) and row[k] for k in ("id", "name")):
                raise ValueError("Brak tożsamości kontenera")
            ports = row.get("ports")
            if ports is None:
                continue
            if not isinstance(ports, dict):
                raise ValueError("Nieprawidłowe porty Docker")
            for key, bindings in ports.items():
                try:
                    _, proto = key.split("/")
                    if proto not in ("tcp", "udp") or bindings is None:
                        continue
                    if not isinstance(bindings, list):
                        raise ValueError("Nieprawidłowe mapowania Docker")
                    for binding in bindings:
                        try:
                            item = _binding(row, key, binding)
                            if item is not None:
                                mappings.add(item)
                        except (ValueError, KeyError, TypeError):
                            if not tolerant:
                                raise
                            invalid = True
                except (ValueError, KeyError, TypeError):
                    if not tolerant:
                        raise
                    invalid = True
        except (ValueError, KeyError, TypeError):
            if not tolerant:
                raise
            invalid = True
    return tuple(
        sorted(
            mappings,
            key=lambda p: (
                p.host_port,
                p.proto,
                p.host_bind,
                p.container_id,
                p.container_port,
            ),
        )
    ), invalid


def parse_inspect(output: str) -> tuple[DockerPort, ...]:
    """Strict public parser; collection uses the same parser with partial recovery."""
    return _parse(output, tolerant=False)[0]


def collect_docker(*, timeout: float = 3.0) -> Collection[DockerPort]:
    """Read local sockets only, sharing one deadline across context, ps and batches."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatni i skończony")
    deadline = time.monotonic() + timeout
    items: list[DockerPort] = []
    failures: list[str] = []

    def remaining() -> float:
        """Stop starting commands once the collector's budget is exhausted."""
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise subprocess.TimeoutExpired("docker", timeout)
        return budget

    try:
        endpoint = _endpoint(remaining())
        if not endpoint.startswith(("unix:///", "npipe:////./pipe/")):
            return Collection(
                (),
                SourceReport(
                    "docker",
                    "unavailable",
                    "Pominięto nielokalny endpoint Docker.",
                    code="remote_endpoint",
                ),
            )
        prefix = ["--host", endpoint]
        rows = _run([*prefix, "ps", "--quiet", "--no-trunc"], remaining())
        ids = list(dict.fromkeys(rows.split()))
        if any(not re.fullmatch(r"[0-9a-f]{12,64}", value) for value in ids):
            raise ValueError("Nieprawidłowy identyfikator Docker")
        for offset in range(0, len(ids), 64):
            try:
                output = _run(
                    [
                        *prefix,
                        "inspect",
                        "--type",
                        "container",
                        "--format",
                        _INSPECT_FORMAT,
                        *ids[offset : offset + 64],
                    ],
                    remaining(),
                )
            except subprocess.CalledProcessError as error:
                output = error.stdout or ""
                failures.append("command_failed")
            parsed, invalid = _parse(output, tolerant=True)
            items.extend(parsed)
            if invalid:
                failures.append("invalid_data")
    except FileNotFoundError:
        failures.append("not_found")
    except (
        subprocess.SubprocessError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        failures.append(error_code(error))
    if failures:
        return Collection(
            tuple(items),
            SourceReport(
                "docker",
                "partial"
                if items
                else "unavailable"
                if failures == ["not_found"]
                else "error",
                "Niepełny odczyt Docker: " + ", ".join(dict.fromkeys(failures)) + ".",
                code=failures[-1],
            ),
        )
    return Collection(tuple(items), SourceReport("docker", "ok"))
