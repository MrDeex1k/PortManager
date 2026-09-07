"""Wykrywanie lokalnych connectorów; bez API Cloudflare, tokenów i zmian tuneli."""

import math
import re
import sys
from dataclasses import replace
from http.client import HTTPException
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

import psutil
import yaml

from portscanner.core.k8s import executable_name
from portscanner.core.model import Collection, SourceReport, TunnelInfo, TunnelRoute

_MAX_CONFIG = 1024 * 1024
_MAX_METRICS = 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _flag(args: tuple[str, ...], flag: str) -> str | None:
    for index, arg in enumerate(args):
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
        if arg == flag and index + 1 < len(args):
            return args[index + 1]
    return None


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
    routes = []
    for rule in ingress:
        if not isinstance(rule, dict) or not isinstance(rule.get("service"), str):
            raise ValueError("Nieprawidłowa reguła ingress")
        service = rule["service"]
        if service.startswith(("unix:", "unix+tls:", "http_status:")) or service in (
            "hello_world",
            "bastion",
        ):
            continue
        parsed = urlsplit(service)
        defaults = {"http": 80, "https": 443, "ssh": 22, "rdp": 3389, "smb": 445}
        if parsed.scheme not in (*defaults, "tcp") or not parsed.hostname:
            raise ValueError("Nieobsługiwany origin ingress")
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
        routes.append(TunnelRoute(pid, hostname, parsed.hostname, port, path))
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
    """Tylko numeryczny loopback, bez proxy, DNS i przekierowań HTTP."""
    if not math.isfinite(timeout) or timeout <= 0 or not 1 <= port <= 65535:
        raise ValueError("Nieprawidłowy timeout lub port")
    address = ip_address(host)
    if not address.is_loopback:
        raise ValueError("Metryki muszą być na loopback")
    authority = f"[{address}]" if address.version == 6 else str(address)
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(f"http://{authority}:{port}/metrics", timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("Nieprawidłowy status metryk")
        payload = response.read(_MAX_METRICS + 1)
    if len(payload) > _MAX_METRICS:
        raise ValueError("Metryki przekraczają limit")
    return parse_metrics(payload.decode("utf-8"))


def _config(
    process: psutil.Process, args: tuple[str, ...]
) -> tuple[object, Literal["explicit", "inferred", "unavailable"]]:
    explicit = _flag(args, "--config")
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
        try:
            with path.open("rb") as stream:
                payload = stream.read(_MAX_CONFIG + 1)
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
    # Własność PID ma pierwszeństwo nad zgadywaniem stałego portu 20241.
    endpoints = set()
    for connection in process.net_connections(kind="tcp"):
        if connection.status != psutil.CONN_LISTEN or not connection.laddr:
            continue
        address = ip_address(connection.laddr.ip)
        if address.is_unspecified:
            host = "127.0.0.1" if address.version == 4 else "::1"
        elif address.is_loopback:
            host = str(address)
        else:
            continue
        endpoints.add((host, connection.laddr.port))
    for host, port in sorted(endpoints)[:8]:
        try:
            return "ok", read_metrics(host, port, timeout=timeout)
        except (OSError, URLError, HTTPException, ValueError):
            continue
    return ("error" if endpoints else "unavailable"), None


def _host_namespace(pid: int) -> bool:
    # W kontenerze localhost i ścieżki konfiguracji mogą znaczyć coś innego.
    if sys.platform != "linux":
        return True
    try:
        return all(
            Path(f"/proc/{pid}/ns/{kind}").stat().st_ino
            == Path(f"/proc/self/ns/{kind}").stat().st_ino
            for kind in ("net", "mnt")
        )
    except OSError:
        return False


def collect_tunnels(
    *, metrics: bool = True, timeout: float = 1.0
) -> Collection[TunnelInfo]:
    """Wykryj procesy cloudflared i ich lokalne reguły; brak procesu = brak tunelu.

    Konfiguracja domyślna jest jedynie inferred: plik może zmienić się po starcie.
    Tryb tokenowy/quick tunnel może nie udostępniać hostname. Metryki sprawdzamy
    wyłącznie na gniazdach przypisanych PID (maks. 8, timeout na każde żądanie).
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatni i skończony")
    items = []
    partial = False
    try:
        for process in psutil.process_iter(attrs=["name", "cmdline"], ad_value=None):
            try:
                info = process.info
                args = tuple(info.get("cmdline") or ())
                names = {executable_name(info.get("name") or "")}
                if args:
                    names.add(executable_name(args[0]))
                if "cloudflared" not in names:
                    if not info.get("name") and not args:
                        partial = True
                    continue
                # Komendy administracyjne CLI nie są działającymi connectorami.
                if args and "tunnel" not in args:
                    continue
                commands = {
                    "run",
                    "login",
                    "create",
                    "delete",
                    "list",
                    "info",
                    "token",
                    "version",
                    "route",
                    "ingress",
                    "cleanup",
                }
                # Nazwa tunelu po `run` może być np. `info`.
                command = next((arg for arg in args[1:] if arg in commands), None)
                if (
                    command not in (None, "run")
                    or "--help" in args
                    or "--version" in args
                ):
                    continue
                tunnel = TunnelInfo(process.pid)
                if not _host_namespace(process.pid):
                    items.append(tunnel)
                    partial = True
                    continue
                token_mode = any(
                    arg == "--token"
                    or arg.startswith("--token=")
                    or arg == "--token-file"
                    or arg.startswith("--token-file=")
                    for arg in args
                )
                if token_mode:
                    tunnel = replace(tunnel, config_status="remote")
                elif args:
                    try:
                        config, status = _config(process, args)
                        routes = parse_ingress(config, process.pid)
                        quick_url = _flag(args, "--url")
                        if quick_url and not routes:
                            routes = parse_ingress(
                                {"ingress": [{"service": quick_url}]}, process.pid
                            )
                        tunnel = replace(tunnel, routes=routes, config_status=status)
                    except (
                        OSError,
                        psutil.Error,
                        ValueError,
                        yaml.YAMLError,
                        RecursionError,
                    ):
                        tunnel = replace(tunnel, config_status="error")
                if metrics:
                    try:
                        metrics_status, connections = _metrics_for(
                            process, timeout=timeout
                        )
                        tunnel = replace(
                            tunnel,
                            metrics_status=metrics_status,
                            connections=connections,
                        )
                    except (OSError, psutil.Error, ValueError):
                        tunnel = replace(tunnel, metrics_status="unavailable")
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
        ),
    )
