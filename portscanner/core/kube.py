"""Opcjonalne mapowania klastra i lokalnych sesji kubectl port-forward."""

import json
import math
import re
import subprocess
import time
from dataclasses import replace
from ipaddress import ip_address
from pathlib import PureWindowsPath
from typing import Any

from portscanner.core.model import (
    Collection,
    KubernetesPort,
    LocalIP,
    PortEntry,
    SourceReport,
)


def _port(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Nieprawidłowy port Kubernetes")
    return value


def _items(output: str) -> list[dict[str, Any]]:
    data = json.loads(output)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("Nieprawidłowa lista Kubernetes")
    if not all(isinstance(item, dict) for item in data["items"]):
        raise ValueError("Nieprawidłowy rekord Kubernetes")
    return data["items"]


def _name(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Brak nazwy Kubernetes")
    return value


def parse_nodeports(
    services: str, nodes: str, local_ips: tuple[LocalIP, ...]
) -> tuple[PortEntry, ...]:
    """Konfiguracja tylko dla IP lokalnego węzła; bez przypisywania PID hosta."""
    local = {ip_address(ip.address) for ip in local_ips}
    local_nodes: set[tuple[str, str]] = set()
    for node in _items(nodes):
        name = _name(node["metadata"]["name"])
        for address in node.get("status", {}).get("addresses", []):
            if address.get("type") not in ("InternalIP", "ExternalIP"):
                continue
            ip = ip_address(address["address"])
            if ip in local and not ip.is_loopback and not ip.is_unspecified:
                local_nodes.add((name, str(ip)))
    groups: dict[tuple[str, str, int], list[KubernetesPort]] = {}
    for service in _items(services):
        metadata, spec = service["metadata"], service["spec"]
        if spec.get("type") not in ("NodePort", "LoadBalancer"):
            continue
        namespace, name = _name(metadata["namespace"]), _name(metadata["name"])
        for item in spec.get("ports", []):
            protocol = item.get("protocol", "TCP")
            if protocol not in ("TCP", "UDP") or not item.get("nodePort"):
                continue
            proto = "tcp" if protocol == "TCP" else "udp"
            node_port, service_port = _port(item["nodePort"]), _port(item["port"])
            for node_name, bind in sorted(local_nodes):
                mapping = KubernetesPort(
                    kind="nodeport",
                    namespace=namespace,
                    resource=f"service/{name}",
                    remote_port=str(service_port),
                    node=node_name,
                )
                groups.setdefault((proto, bind, node_port), []).append(mapping)
    return tuple(
        PortEntry(
            "tcp" if proto == "tcp" else "udp",
            bind,
            port,
            origin="kubernetes",
            kubernetes=tuple(dict.fromkeys(mappings)),
        )
        for (proto, bind, port), mappings in sorted(groups.items())
    )


_VALUE_FLAGS = {
    "-n",
    "--namespace",
    "--context",
    "--kubeconfig",
    "--address",
    "--pod-running-timeout",
    "--request-timeout",
    "--as",
    "--as-group",
    "--cluster",
    "--user",
    "--server",
    "-s",
    "--token",
    "--certificate-authority",
    "--client-certificate",
    "--client-key",
    "--tls-server-name",
    "--v",
    "-v",
}
_BOOL_FLAGS = {"--insecure-skip-tls-verify", "--disable-compression"}


def port_forward(entry: PortEntry) -> tuple[KubernetesPort, ...]:
    """Informacja z cmdline wyłącznie dla zaobserwowanego gniazda tego PID.

    Nie rozwiązujemy bieżącego kubeconfig dla już działającego procesu.
    Nieznane opcje i losowo wybrane porty są pomijane bez zgadywania.
    """
    process = entry.process
    if (
        entry.origin != "socket"
        or entry.proto != "tcp"
        or entry.pid is None
        or process is None
        or process.pid != entry.pid
        or not process.cmdline
        or PureWindowsPath(process.name or "").name.lower()
        not in ("kubectl", "kubectl.exe")
        or PureWindowsPath(process.cmdline[0]).name.lower()
        not in ("kubectl", "kubectl.exe")
    ):
        return ()
    positional: list[str] = []
    options: dict[str, str] = {}
    args = iter(process.cmdline[1:])
    for arg in args:
        if arg == "--":
            positional.extend(args)
            break
        if arg.startswith("-"):
            flag, separator, value = arg.partition("=")
            if (
                not separator
                and flag.startswith("-n")
                and not flag.startswith("--")
                and len(flag) > 2
            ):
                flag, separator, value = "-n", "=", flag[2:]
            if flag in _BOOL_FLAGS:
                continue
            if flag not in _VALUE_FLAGS:
                return ()
            if not separator:
                value = next(args, "")
            if not value or value.startswith("-"):
                return ()
            options["--namespace" if flag == "-n" else flag] = value
        else:
            positional.append(arg)
    if len(positional) < 3 or positional[0] != "port-forward":
        return ()
    resource = positional[1]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./_-]*", resource):
        return ()
    mappings = []
    for value in positional[2:]:
        local, separator, remote = value.partition(":")
        if not separator:
            remote = local
        if (
            len(local) > 5
            or not local.isascii()
            or not local.isdigit()
            or int(local) != entry.port
            or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]*", remote)
        ):
            continue
        if remote.isdigit() and not 1 <= int(remote) <= 65535:
            continue
        mappings.append(
            KubernetesPort(
                kind="port-forward",
                namespace=options.get("--namespace"),
                resource=resource,
                remote_port=remote,
                context=options.get("--context"),
            )
        )
    return tuple(dict.fromkeys(mappings))


def _run(resource: str, timeout: float) -> str:
    result = subprocess.run(
        [
            "kubectl",
            "get",
            resource,
            "--all-namespaces",
            "--output=json",
            f"--request-timeout={timeout:.3f}s",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=True,
    )
    if len(result.stdout.encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError("Zbyt duża odpowiedź Kubernetes")
    return result.stdout


def collect_kube(
    entries: tuple[PortEntry, ...],
    local_ips: tuple[LocalIP, ...],
    *,
    timeout: float = 3.0,
) -> Collection[PortEntry]:
    """Jawny odczyt bieżącego kontekstu; wspólny budżet dla services i nodes.

    Kubectl obsługuje kubeconfig i uwierzytelnienie (w tym pluginy exec).
    Nie ujawniamy stderr ani konfiguracji zawierającej poświadczenia.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatni i skończony")
    enriched = tuple(
        replace(entry, kubernetes=port_forward(entry)) for entry in entries
    )
    has_forward = any(entry.kubernetes for entry in enriched)
    deadline = time.monotonic() + timeout
    try:
        services = _run("services", timeout)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("kubectl", timeout)
        nodes = _run("nodes", remaining)
        mappings = parse_nodeports(services, nodes, local_ips)
    except FileNotFoundError:
        report = SourceReport(
            "kubernetes", "partial" if has_forward else "unavailable", "Brak kubectl."
        )
    except (
        subprocess.SubprocessError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
    ):
        report = SourceReport(
            "kubernetes",
            "partial" if has_forward else "error",
            "Odczyt klastra niedostępny (kubeconfig, uprawnienia, timeout lub dane). "
            "Lokalne sesje port-forward pozostają widoczne.",
        )
    else:
        return Collection(
            enriched + mappings,
            SourceReport(
                "kubernetes",
                "ok",
                "NodePort: konfiguracja dla lokalnych IP węzłów, "
                "bez weryfikacji dostępności.",
            ),
        )
    return Collection(enriched, report)
