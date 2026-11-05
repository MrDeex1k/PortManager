"""Wykrywanie lokalnych connectorów; bez API Cloudflare, tokenów i zmian tuneli."""

import math
import os
import re
import socket
import subprocess
import threading
import time
from dataclasses import replace
from http.client import HTTPConnection, HTTPException
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import psutil
import yaml

from portscanner.core.command import read_regular_file
from portscanner.core.discovery_errors import DiscoveryError, error_code
from portscanner.core.k8s import executable_name
from portscanner.core.model import Collection, SourceReport, TunnelInfo, TunnelRoute
from portscanner.core.namespaces import same_namespaces

_MAX_CONFIG = 1024 * 1024
_MAX_METRICS = 1024 * 1024


_VALUE_FLAGS = {
    "--config",
    "--url",
    "--metrics",
    "--logfile",
    "--log-directory",
    "--loglevel",
    "--transport-loglevel",
    "--origincert",
    "--pidfile",
    "--token",
    "--token-file",
    "--credentials-file",
    "--cred-file",
    "--credentials-contents",
    "--protocol",
    "--edge-ip-version",
    "--region",
    "--hostname",
    "--name",
    "--label",
    "--tag",
    "--tags",
    "--grace-period",
    "--retries",
    "--autoupdate-freq",
    "--unix-socket",
    "--http-host-header",
    "--origin-server-name",
    "--proxy-connect-timeout",
    "--proxy-tls-timeout",
    "--proxy-keepalive-timeout",
    "--proxy-keepalive-connections",
    "--proxy-address",
    "--proxy-port",
    "--proxy-type",
    "--origin-ca-pool",
    "--quick-service",
    "--edge-bind-address",
    "--icmpv4-src",
    "--icmpv6-src",
    "--ha-connections",
    "--dns-resolver-addrs",
    "--max-active-flows",
    "--management-hostname",
    "--output",
    "--log-format",
    "--feature",
    "--features",
    "-p",
    "-F",
}
_BOOL_FLAGS = {
    "--no-autoupdate",
    "--hello-world",
    "--bastion",
    "--no-tls-verify",
    "--no-chunked-encoding",
    "--http2-origin",
    "--post-quantum",
    "--pq",
    "--no-prechecks",
    "--proxy-no-happy-eyeballs",
    "--force",
    "--fips",
    "--management-diagnostics",
    "--stdin-control",
    "--socks5",
}


def _arguments(args: tuple[str, ...]) -> tuple[bool | None, dict[str, str]]:
    """Return None for unrecognized arguments, False for non-connector commands."""
    positional = []
    options = {}
    values = iter(args[1:])
    for arg in values:
        if arg == "--":
            positional.extend(values)
            break
        if arg.startswith("-"):
            flag, separator, value = arg.partition("=")
            if flag in _BOOL_FLAGS:
                options[flag] = value if separator else "true"
                continue
            if flag not in _VALUE_FLAGS:
                return None, {}
            if not separator:
                value = next(values, "")
            if not value:
                return None, {}
            options[flag] = value
        else:
            positional.append(arg)
    return bool(
        positional
        and positional[0] == "tunnel"
        and (len(positional) == 1 or positional[1] == "run")
    ), options


def parse_ingress(config: object, pid: int) -> tuple[TunnelRoute, ...]:
    """Zachowaj kolejność reguł. Bez DNS i bez odczytu credentials-file.

    Reguły do Unix sockets i odpowiedzi wbudowanych nie mają portu TCP.
    Nazwy origin inne niż localhost zachowujemy, ale nie rozwiązujemy DNS.
    """
    if not isinstance(config, dict):
        raise ValueError("Konfiguracja musi być mapą")
    ingress = config.get("ingress", [])
    if not isinstance(ingress, list):
        raise ValueError("Ingress musi być listą")
    origin_defaults = config.get("originRequest") or {}
    if not isinstance(origin_defaults, dict):
        raise ValueError("Nieprawidłowe originRequest")
    routes = []
    for rule in ingress:
        if not isinstance(rule, dict) or not isinstance(rule.get("service"), str):
            raise ValueError("Nieprawidłowa reguła ingress")
        service = rule["service"]
        settings = rule.get("originRequest") or {}
        if not isinstance(settings, dict):
            raise ValueError("Nieprawidłowe originRequest")
        bastion = settings.get("bastionMode", origin_defaults.get("bastionMode", False))
        if type(bastion) is not bool:
            raise ValueError("Nieprawidłowe bastionMode")
        if bastion:
            continue
        if service.startswith(("unix:", "unix+tls:", "http_status:")) or service in (
            "hello_world",
            "hello-world",
            "socks-proxy",
            "bastion",
        ):
            continue
        parsed = urlsplit(service)
        defaults = {"http": 80, "https": 443, "ssh": 22, "rdp": 3389, "smb": 445}
        if parsed.scheme not in (*defaults, "tcp") or not parsed.hostname:
            raise DiscoveryError("unsupported_origin")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "Origin z danymi uwierzytelniającymi nie jest eksportowany"
            )
        port = parsed.port if parsed.port is not None else defaults.get(parsed.scheme)
        if port is None or not 1 <= port <= 65535:
            raise ValueError("Nieprawidłowy port origin")
        hostname, path = rule.get("hostname"), rule.get("path")
        if (hostname is not None and not isinstance(hostname, str)) or (
            path is not None and not isinstance(path, str)
        ):
            raise ValueError("Nieprawidłowe dopasowanie reguły")
        host = parsed.hostname
        # URL zone separators are encoded as %25; OS addresses use %.
        # Decode only IPv6 zones, never arbitrary origin hostnames.
        if ":" in host and "%25" in host:
            host = host.replace("%25", "%", 1)
        routes.append(TunnelRoute(pid, hostname, host, port, path))
    return tuple(routes)


def parse_metrics(text: str) -> int:
    """Odczytaj gauge aktywnych połączeń; brak metryki nie oznacza zera."""
    values = []
    for line in text.splitlines():
        match = re.fullmatch(
            r"cloudflared_tunnel_ha_connections(?:\{[^\n]*\})?\s+(\S+)(?:\s+\S+)?",
            line.strip(),
        )
        if match:
            value = float(match[1])
            if not math.isfinite(value) or value < 0 or not value.is_integer():
                raise ValueError("Nieprawidłowa metryka")
            values.append(int(value))
    if not values:
        raise ValueError("Brak metryki połączeń")
    return sum(values)


def read_metrics(host: str, port: int, *, timeout: float = 1.0) -> int:
    """Read numeric loopback without proxies/redirects; cancel slow HTTP at deadline."""
    if not math.isfinite(timeout) or timeout <= 0 or not 1 <= port <= 65535:
        raise ValueError("Nieprawidłowy timeout lub port")
    address = ip_address(host)
    if not address.is_loopback:
        raise ValueError("Metryki muszą być na loopback")
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    connection = HTTPConnection(str(address), port, timeout=timeout)
    connection.sock = sock  # Connect directly: no DNS or environment proxy lookup.
    expired = threading.Event()

    def cancel() -> None:
        """Interrupt headers and body reads, including a byte-at-a-time sender."""
        expired.set()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()

    timer = threading.Timer(timeout, cancel)
    timer.daemon = True
    timer.start()
    try:
        sock.settimeout(timeout)
        sock.connect((str(address), port))
        connection.request("GET", "/metrics")
        with connection.getresponse() as response:
            if response.status != 200:
                raise HTTPError(
                    "/metrics",
                    response.status,
                    "metrics_http_status",
                    response.headers,
                    None,
                )
            payload = response.read(_MAX_METRICS + 1)
        if expired.is_set():
            raise TimeoutError("metrics deadline")
        if len(payload) > _MAX_METRICS:
            raise DiscoveryError("output_limit")
        return parse_metrics(payload.decode("utf-8"))
    except Exception:
        if expired.is_set():
            raise TimeoutError("metrics deadline") from None
        raise
    finally:
        timer.cancel()
        timer.join()
        connection.close()
        sock.close()


def _config(
    process: psutil.Process, args: tuple[str, ...], *, timeout: float = 1.0
) -> tuple[object, Literal["explicit", "inferred", "unavailable"]]:
    """Read only regular files within a shared I/O deadline, never token files."""
    deadline = time.monotonic() + timeout
    explicit = _arguments(args)[1].get("--config")
    if explicit is not None:
        path = Path(explicit)
        if not path.is_absolute():
            path = Path(process.cwd()) / path
        paths = [path]
    else:
        paths = []
        if process.username() == psutil.Process().username():
            paths.extend(
                [
                    Path.home() / ".cloudflared" / "config.yml",
                    Path.home() / ".cloudflared" / "config.yaml",
                ]
            )
        paths.extend(
            Path(root) / name
            for root in ("/etc/cloudflared", "/usr/local/etc/cloudflared")
            for name in ("config.yml", "config.yaml")
        )
    for path in paths:
        if explicit is None:
            try:
                os.lstat(path)
            except FileNotFoundError:
                continue
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("config deadline")
            payload = read_regular_file(str(path), timeout=remaining, limit=_MAX_CONFIG)
        except FileNotFoundError:
            if explicit is not None:
                raise
            continue
        if len(payload) > _MAX_CONFIG:
            raise ValueError("Konfiguracja przekracza limit")
        config = yaml.safe_load(payload)
        return config, "explicit" if explicit is not None else "inferred"
    return {}, "unavailable"


def _metrics_for(
    process: psutil.Process, *, timeout: float
) -> tuple[Literal["ok", "unavailable", "error"], int | None]:
    """Probe at most eight owned endpoints within the remaining collector budget."""
    deadline = time.monotonic() + timeout
    # Własność PID ma pierwszeństwo nad zgadywaniem stałego portu 20241.
    endpoints = set()
    for connection in process.net_connections(kind="tcp"):
        if connection.status != psutil.CONN_LISTEN or not connection.laddr:
            continue
        try:
            address = ip_address(connection.laddr.ip)
        except ValueError:
            continue
        if address.is_unspecified:
            host = "127.0.0.1" if address.version == 4 else "::1"
        elif address.is_loopback:
            host = str(address)
        else:
            continue
        endpoints.add((host, connection.laddr.port))
    failure = "metrics_unavailable"
    for host, port in sorted(endpoints)[:8]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failure = "timeout"
            break
        try:
            return "ok", read_metrics(host, port, timeout=remaining)
        except (OSError, URLError, HTTPException, ValueError) as error:
            failure = (
                "http_status" if isinstance(error, HTTPError) else error_code(error)
            )
    if endpoints:
        raise DiscoveryError(failure)
    return "unavailable", None


def _host_namespace(pid: int) -> bool:
    # W kontenerze localhost i ścieżki konfiguracji mogą znaczyć coś innego.
    try:
        return same_namespaces(pid)
    except OSError:
        return False


def collect_tunnels(
    *, metrics: bool = True, timeout: float = 1.0
) -> Collection[TunnelInfo]:
    """Read connector metadata using one shared budget for config and metrics I/O."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatni i skończony")
    deadline = time.monotonic() + timeout
    items = []
    partial = False

    def remaining() -> float:
        """Do not start another I/O operation after the collector deadline."""
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("tunnel deadline")
        return value

    try:
        for process in psutil.process_iter(attrs=["name", "cmdline"], ad_value=None):
            try:
                info = process.info
                args = tuple(info.get("cmdline") or ())
                names = {executable_name(info.get("name") or "")}
                if args:
                    names.add(executable_name(args[0]))
                if "cloudflared" not in names:
                    partial |= not info.get("name") and not args
                    continue
                connector, options = _arguments(args)
                if args and connector is None:
                    partial = True
                    continue
                if args and not connector:
                    continue
                tunnel = TunnelInfo(process.pid)
                if not _host_namespace(process.pid):
                    items.append(
                        replace(
                            tunnel,
                            config_code="namespace_unavailable",
                            metrics_code="namespace_unavailable",
                        )
                    )
                    partial = True
                    continue
                try:
                    remaining()
                    # Keep only presence booleans. Do not retain environment secrets.
                    remote = bool(options.get("--token") or options.get("--token-file"))
                    if not remote:
                        env = process.environ()
                        remote = bool(
                            env.get("TUNNEL_TOKEN") or env.get("TUNNEL_TOKEN_FILE")
                        )
                        del env
                    if remote:
                        tunnel = replace(tunnel, config_status="remote")
                    elif args:
                        config, status = _config(process, args, timeout=remaining())
                        if isinstance(config, dict) and (
                            config.get("token") or config.get("token-file")
                        ):
                            tunnel = replace(tunnel, config_status="remote")
                        else:
                            routes = parse_ingress(config, process.pid)
                            quick_url = options.get("--url")
                            if quick_url and not routes:
                                if "://" not in quick_url:
                                    quick_url = "http://" + quick_url
                                routes = parse_ingress(
                                    {"ingress": [{"service": quick_url}]}, process.pid
                                )
                            tunnel = replace(
                                tunnel, routes=routes, config_status=status
                            )
                except (
                    OSError,
                    psutil.Error,
                    ValueError,
                    yaml.YAMLError,
                    RecursionError,
                    subprocess.SubprocessError,
                ) as error:
                    code = (
                        "environment_unavailable"
                        if isinstance(error, psutil.Error)
                        else error_code(error)
                    )
                    tunnel = replace(tunnel, config_status="error", config_code=code)
                if metrics:
                    try:
                        status, connections = _metrics_for(process, timeout=remaining())
                        tunnel = replace(
                            tunnel,
                            metrics_status=status,
                            connections=connections,
                            metrics_code=None
                            if status == "ok"
                            else "metrics_unavailable",
                        )
                    except (OSError, psutil.Error, ValueError) as error:
                        status = (
                            "unavailable"
                            if isinstance(error, psutil.Error)
                            else "error"
                        )
                        tunnel = replace(
                            tunnel,
                            metrics_status=status,
                            metrics_code=error_code(error),
                        )
                else:
                    tunnel = replace(tunnel, metrics_status="disabled")
                if not process.is_running():
                    partial = True
                    continue
                partial |= (
                    tunnel.config_status != "explicit"
                    or tunnel.metrics_status not in ("ok", "disabled")
                )
                items.append(tunnel)
            except (psutil.Error, OSError):
                partial = True
    except (psutil.Error, OSError):
        return Collection(
            tuple(items),
            SourceReport(
                "tunnels",
                "partial" if items else "error",
                "Nie udało się odczytać pełnej listy procesów tuneli.",
                code="process_scan_failed",
            ),
        )
    return Collection(
        tuple(sorted(items, key=lambda item: item.pid)),
        SourceReport(
            "tunnels",
            "partial" if partial else "ok",
            "Niepełna widoczność konfiguracji, procesów lub metryk."
            if partial
            else None,
            code="partial_read" if partial else None,
        ),
    )
