"""Adresy interfejsów i jawny, niezależny odczyt exit IP przez HTTPS."""

import math
import socket
from http.client import HTTPException
from ipaddress import ip_address
from urllib.error import URLError
from urllib.request import Request, urlopen

import psutil

from portscanner.core.model import ExitIP, LocalIP

EXIT_IP_URL = "https://api64.ipify.org"
_MAX_RESPONSE_BYTES = 64


class LocalIPError(RuntimeError):
    """Nie udało się odczytać adresów interfejsów."""


class ExitIPError(RuntimeError):
    """Exit IP jest niedostępny lub usługa zwróciła nieprawidłową odpowiedź."""


def collect_local_ips() -> list[LocalIP]:
    """Zwróć wszystkie przypisane IPv4/IPv6, także loopback, VPN i link-local.

    Bez DNS i żądań sieciowych. Nie wybiera jednego 'głównego' IP i nie
    odrzuca interfejsów nieaktywnych; zachowuje scope IPv6 zwrócony przez OS.
    """
    entries: set[LocalIP] = set()
    try:
        for interface, addresses in psutil.net_if_addrs().items():
            for address in addresses:
                if address.family not in (socket.AF_INET, socket.AF_INET6):
                    continue
                parsed = ip_address(address.address)
                entries.add(
                    LocalIP(
                        interface=interface,
                        address=str(parsed),
                        family="ipv4" if parsed.version == 4 else "ipv6",
                    )
                )
    except (psutil.Error, OSError, ValueError) as exc:
        raise LocalIPError("Nie udało się odczytać lokalnych adresów IP.") from exc
    return sorted(
        entries, key=lambda entry: (entry.interface, entry.family, entry.address)
    )


def fetch_exit_ip(*, timeout: float = 3.0) -> ExitIP:
    """Wyślij jawne żądanie do ipify; odczyty lokalne nie wywołują tej funkcji.

    Wynik to jeden IPv4 lub IPv6 zależnie od trasy do usługi, w tym VPN/proxy.
    urllib respektuje konfigurację proxy systemu/środowiska. Timeout dotyczy
    operacji blokujących gniazda, nie stanowi twardego limitu czasu całej
    funkcji (np. rozwiązywania DNS). Bez retry, cache i globalnych timeoutów.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout musi być dodatnią, skończoną liczbą sekund.")

    request = Request(EXIT_IP_URL, headers={"Accept": "text/plain"})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ExitIPError("Usługa exit IP zwróciła nieprawidłowy status HTTP.")
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
    except (URLError, OSError, HTTPException) as exc:
        raise ExitIPError(
            "Nie udało się pobrać exit IP; sprawdź połączenie z siecią."
        ) from exc

    if len(payload) > _MAX_RESPONSE_BYTES:
        raise ExitIPError("Odpowiedź usługi exit IP jest zbyt długa.")
    try:
        address = ip_address(payload.decode("ascii").strip())
    except ValueError as exc:
        raise ExitIPError("Usługa exit IP nie zwróciła poprawnego adresu IP.") from exc
    if not address.is_global or address.is_multicast or "%" in str(address):
        raise ExitIPError("Usługa exit IP nie zwróciła publicznego adresu IP.")
    return ExitIP(
        address=str(address),
        family="ipv4" if address.version == 4 else "ipv6",
        source=EXIT_IP_URL,
    )
