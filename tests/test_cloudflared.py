"""Tunele: konfiguracja nie jest dowodem dostępności publicznej."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import psutil
import pytest

from portscanner.core import cloudflared as cf


def test_ingress_keeps_order_path_and_catchall_without_network() -> None:
    routes = cf.parse_ingress(
        {
            "ingress": [
                {
                    "hostname": "app.example.com",
                    "path": "/api",
                    "service": "http://localhost:8080",
                },
                {"hostname": "*.example.com", "service": "https://[::1]"},
                {"service": "tcp://192.168.1.10:5432"},
                {"service": "unix:/tmp/web.sock"},
                {"service": "http_status:404"},
            ]
        },
        42,
    )
    assert [(r.hostname, r.host, r.port, r.path) for r in routes] == [
        ("app.example.com", "localhost", 8080, "/api"),
        ("*.example.com", "::1", 443, None),
        (None, "192.168.1.10", 5432, None),
    ]


@pytest.mark.parametrize(
    "config",
    [
        None,
        [],
        {"ingress": {}},
        {"ingress": [None]},
        {"ingress": [{"service": "http://user:secret@localhost:80"}]},
        {"ingress": [{"service": "tcp://localhost"}]},
        {"ingress": [{"service": "http://localhost:99999"}]},
    ],
)
def test_invalid_ingress_is_rejected(config: object) -> None:
    with pytest.raises(ValueError):
        cf.parse_ingress(config, 42)


@pytest.mark.parametrize(
    "text,count",
    [
        ("# HELP gauge\ncloudflared_tunnel_ha_connections 4\n", 4),
        (
            'cloudflared_tunnel_ha_connections{tunnel="a"} 2\n'
            'cloudflared_tunnel_ha_connections{tunnel="b"} 1',
            3,
        ),
        ("cloudflared_tunnel_ha_connections 0", 0),
    ],
)
def test_metrics_parse_active_connections(text: str, count: int) -> None:
    assert cf.parse_metrics(text) == count


@pytest.mark.parametrize(
    "text",
    [
        "other_metric 4",
        "cloudflared_tunnel_ha_connections NaN",
        "cloudflared_tunnel_ha_connections -1",
        "cloudflared_tunnel_ha_connections 0.5",
    ],
)
def test_missing_or_invalid_metric_is_not_zero(text: str) -> None:
    with pytest.raises(ValueError):
        cf.parse_metrics(text)


def test_metrics_disable_proxy_redirects_and_bound_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = b"cloudflared_tunnel_ha_connections 4"
    connection = Mock()
    connection.getresponse.return_value = response
    builder = Mock(return_value=connection)
    sock = Mock()
    monkeypatch.setattr(cf, "HTTPConnection", builder)
    monkeypatch.setattr(cf.socket, "socket", Mock(return_value=sock))
    dns = Mock(side_effect=AssertionError("No DNS lookup"))
    monkeypatch.setattr(cf.socket, "getaddrinfo", dns)
    assert cf.read_metrics("::1", 20241, timeout=0.5) == 4
    sock.connect.assert_called_once_with(("::1", 20241))
    connection.request.assert_called_once_with("GET", "/metrics")
    dns.assert_not_called()
    response.read.assert_called_once_with(1024 * 1024 + 1)
    response.__exit__.assert_called_once()


@pytest.mark.parametrize("host", ["localhost", "example.com", "192.168.1.2", "0.0.0.0"])
def test_non_loopback_metrics_never_open_http(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    builder = Mock()
    monkeypatch.setattr(cf, "HTTPConnection", builder)
    with pytest.raises(ValueError):
        cf.read_metrics(host, 20241)
    builder.assert_not_called()


@pytest.fixture
def connector(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Mock:
    config = tmp_path / "config.yml"
    config.write_text(
        "ingress:\n  - hostname: app.example.com\n    service: http://localhost:8080\n"
    )
    process = Mock()
    process.pid = 42
    process.info = {
        "name": "cloudflared",
        "cmdline": [
            "/usr/bin/cloudflared",
            "tunnel",
            "--config",
            str(config),
            "run",
            "my-tunnel",
        ],
    }
    process.is_running.return_value = True
    process.environ.return_value = {}
    process.net_connections.return_value = [
        SimpleNamespace(
            status=psutil.CONN_LISTEN, laddr=SimpleNamespace(ip="127.0.0.1", port=20243)
        )
    ]
    monkeypatch.setattr(psutil, "process_iter", Mock(return_value=[process]))
    monkeypatch.setattr(cf, "read_metrics", Mock(return_value=4))
    monkeypatch.setattr(cf, "_host_namespace", Mock(return_value=True))
    return process


def test_connector_uses_config_and_pid_owned_metrics(connector: Mock) -> None:
    result = cf.collect_tunnels()
    assert result.report.status == "ok"
    tunnel = result.items[0]
    assert tunnel.config_status == "explicit"
    assert tunnel.connections == 4 and tunnel.metrics_status == "ok"
    assert tunnel.routes[0].port == 8080


def test_remote_token_does_not_read_local_file_or_export_secret(
    connector: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector.info["cmdline"] = ["cloudflared", "tunnel", "run", "--token", "SECRET"]
    config = Mock(side_effect=AssertionError("Nie czytaj pliku"))
    monkeypatch.setattr(cf, "_config", config)
    result = cf.collect_tunnels()
    assert result.report.status == "partial"
    assert result.items[0].config_status == "remote" and not result.items[0].routes
    assert "SECRET" not in str(result)
    config.assert_not_called()


def test_missing_config_and_denied_metrics_preserve_process(connector: Mock) -> None:
    connector.info["cmdline"] = [
        "cloudflared",
        "tunnel",
        "--config",
        "/missing/config.yml",
        "run",
    ]
    connector.net_connections.side_effect = psutil.AccessDenied(42)
    result = cf.collect_tunnels()
    assert result.items[0].pid == 42
    assert result.items[0].config_status == "error"
    assert result.items[0].metrics_status == "unavailable"
    assert result.report.status == "partial"


def test_process_exit_does_not_leave_stale_tunnel(connector: Mock) -> None:
    connector.is_running.return_value = False
    result = cf.collect_tunnels()
    assert result.items == () and result.report.status == "partial"


def test_unrelated_process_and_admin_command_are_not_tunnels(connector: Mock) -> None:
    connector.info = {"name": "python", "cmdline": ["python", "cloudflared"]}
    assert not cf.collect_tunnels().items
    connector.info = {
        "name": "cloudflared.exe",
        "cmdline": ["cloudflared.exe", "tunnel", "list"],
    }
    assert not cf.collect_tunnels().items


def test_no_process_does_not_read_config_or_probe_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(psutil, "process_iter", Mock(return_value=[]))
    metrics = Mock()
    monkeypatch.setattr(cf, "read_metrics", metrics)
    result = cf.collect_tunnels()
    assert result.report.status == "ok" and not result.items
    metrics.assert_not_called()


def test_yaml_safe_load_rejects_python_tags(connector: Mock, tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text('!!python/object/apply:os.system ["echo should-not-run"]')
    assert cf.collect_tunnels().items[0].config_status == "error"


def test_metrics_can_be_disabled(connector: Mock) -> None:
    result = cf.collect_tunnels(metrics=False)
    assert result.items[0].metrics_status == "disabled"
    connector.net_connections.assert_not_called()


def test_tunnel_name_may_equal_admin_command(connector: Mock) -> None:
    connector.info["cmdline"][-1] = "info"
    assert len(cf.collect_tunnels().items) == 1


def test_explicit_relative_config_uses_connector_cwd(
    connector: Mock, tmp_path: Path
) -> None:
    connector.cwd.return_value = str(tmp_path)
    connector.info["cmdline"] = ["cloudflared", "tunnel", "--config=config.yml", "run"]
    assert cf.collect_tunnels(metrics=False).items[0].routes[0].port == 8080


def test_quick_tunnel_preserves_unknown_hostname(
    connector: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector.info["cmdline"] = ["cloudflared", "tunnel", "--url=http://localhost:3000"]
    monkeypatch.setattr(cf, "_config", Mock(return_value=({}, "unavailable")))
    result = cf.collect_tunnels()
    assert result.items[0].routes[0].hostname is None
    assert result.items[0].routes[0].port == 3000
    assert result.report.status == "partial"


def test_port_zero_is_invalid() -> None:
    with pytest.raises(ValueError):
        cf.parse_ingress({"ingress": [{"service": "http://localhost:0"}]}, 42)


def test_other_namespace_does_not_map_container_localhost(
    connector: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cf, "_host_namespace", Mock(return_value=False))
    result = cf.collect_tunnels()
    assert result.report.status == "partial"
    assert result.items[0].pid == 42 and not result.items[0].routes
    connector.net_connections.assert_not_called()


@pytest.mark.parametrize("succeed", [False, True])
def test_metrics_share_one_budget_across_endpoint_attempts(
    connector: Mock,
    monkeypatch: pytest.MonkeyPatch,
    succeed: bool,
) -> None:
    connector.net_connections.return_value = [
        SimpleNamespace(
            status=psutil.CONN_LISTEN,
            laddr=SimpleNamespace(ip="127.0.0.1", port=20241 + n),
        )
        for n in range(8)
    ]
    now = [100.0]
    monkeypatch.setattr(cf.time, "monotonic", lambda: now[0])

    def attempt(host: str, port: int, *, timeout: float) -> int:
        now[0] += min(2.0, timeout)
        if succeed and port == 20242:
            return 4
        raise TimeoutError("timeout")

    read = Mock(side_effect=attempt)
    monkeypatch.setattr(cf, "read_metrics", read)
    if succeed:
        assert cf._metrics_for(connector, timeout=3.0) == ("ok", 4)
    else:
        with pytest.raises(cf.DiscoveryError, match="timeout"):
            cf._metrics_for(connector, timeout=3.0)
    assert [call.kwargs["timeout"] for call in read.call_args_list] == [3.0, 1.0]
    assert now[0] == 103.0


def test_metrics_skip_bad_addresses_and_preserve_unavailable_status(
    connector: Mock,
) -> None:
    connector.net_connections.return_value = [
        SimpleNamespace(
            status=psutil.CONN_LISTEN, laddr=SimpleNamespace(ip="invalid", port=20241)
        )
    ]
    assert cf._metrics_for(connector, timeout=1.0) == ("unavailable", None)


def test_namespace_read_error_is_not_host_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cf, "same_namespaces", Mock(side_effect=PermissionError()))
    assert not cf._host_namespace(42)


def test_ingress_decodes_only_ipv6_zone_separator():
    from portscanner.core.cloudflared import parse_ingress

    routes = parse_ingress(
        {"ingress": [{"service": "http://[fe80::1%25en0]:8080"}]}, 42
    )
    assert routes[0].host == "fe80::1%en0"
    from portscanner.core.model import PortEntry, TunnelInfo
    from portscanner.core.snapshot import merge_sources

    rows = merge_sources(
        [PortEntry("tcp", "fe80::1%en0", 8080)], (), (TunnelInfo(42, routes),)
    )
    assert rows[0].tunnels == routes


@pytest.mark.parametrize("service", ["hello-world", "socks-proxy"])
def test_builtin_service_preserves_other_routes(service):
    """Non-port builtins never erase unrelated HTTP origins."""
    routes = cf.parse_ingress(
        {
            "ingress": [
                {"hostname": "app.example", "service": "http://localhost:8080"},
                {"service": service},
            ]
        },
        42,
    )
    assert len(routes) == 1 and routes[0].port == 8080


@pytest.mark.parametrize("global_setting", [True, False])
def test_bastion_does_not_invent_static_origin(global_setting):
    """Global and per-rule bastion mode both replace the static service."""
    rule: dict[str, object] = {"service": "http://localhost:8080"}
    config: dict[str, object] = {"ingress": [rule]}
    (config if global_setting else rule)["originRequest"] = {"bastionMode": True}
    assert cf.parse_ingress(config, 42) == ()
    rule["originRequest"] = {"bastionMode": False}
    assert cf.parse_ingress(config, 42)[0].port == 8080


def test_global_bastion_survives_an_explicit_static_rule():
    """One rule overriding bastion mode must not clear defaults for later rules."""
    routes = cf.parse_ingress(
        {
            "originRequest": {"bastionMode": True},
            "ingress": [
                {
                    "service": "http://localhost:8080",
                    "originRequest": {"bastionMode": False},
                },
                {"service": "http://localhost:9090"},
            ],
        },
        42,
    )
    assert [route.port for route in routes] == [8080]


def test_config_filename_is_not_an_admin_command(connector, tmp_path):
    """A relative config named info remains a flag value before tunnel run."""
    (tmp_path / "info").write_text("ingress:\n  - service: http://localhost:8080\n")
    connector.cwd.return_value = str(tmp_path)
    connector.info["cmdline"] = [
        "cloudflared",
        "tunnel",
        "--config",
        "info",
        "run",
        "demo",
    ]
    assert cf.collect_tunnels(metrics=False).items[0].routes[0].port == 8080
    connector.info["cmdline"] = ["cloudflared", "tunnel", "--logfile", "run", "list"]
    assert cf.collect_tunnels(metrics=False).items == ()


@pytest.mark.parametrize("source", ["config", "env", "env_file"])
def test_remote_mode_never_exports_local_routes(connector, tmp_path, source):
    """Token presence is enough; no token file needs to be opened or exported."""
    if source == "config":
        (tmp_path / "config.yml").write_text(
            "token: SYNTHETIC_SECRET\ningress:\n  - service: http://localhost:8080\n"
        )
    else:
        connector.environ.return_value = {
            "TUNNEL_TOKEN"
            if source == "env"
            else "TUNNEL_TOKEN_FILE": "SYNTHETIC_SECRET"
        }
    result = cf.collect_tunnels(metrics=False)
    assert result.items[0].config_status == "remote"
    assert not result.items[0].routes
    assert "SYNTHETIC_SECRET" not in str(result)


def test_unknown_environment_does_not_claim_local_config(connector):
    """An inaccessible environment leaves remote-vs-local provenance uncertain."""
    connector.environ.side_effect = psutil.AccessDenied(42)
    tunnel = cf.collect_tunnels(metrics=False).items[0]
    assert not tunnel.routes and tunnel.config_code == "environment_unavailable"


def test_quick_origin_without_scheme(connector, monkeypatch):
    """CLI origin normalization defaults to HTTP without changing ingress rules."""
    connector.info["cmdline"] = ["cloudflared", "tunnel", "--url", "localhost:3000"]
    monkeypatch.setattr(cf, "_config", Mock(return_value=({}, "unavailable")))
    assert cf.collect_tunnels(metrics=False).items[0].routes[0].port == 3000


def test_all_connectors_share_one_io_budget(connector, monkeypatch):
    """Later connectors remain visible even when the first exhausts the I/O budget."""
    from copy import copy

    second = copy(connector)
    second.pid = 43
    monkeypatch.setattr(
        cf.psutil, "process_iter", Mock(return_value=[connector, second])
    )
    now = [0.0]
    monkeypatch.setattr(cf.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(cf, "_config", Mock(return_value=({}, "explicit")))

    def slow(*args, **kwargs):
        now[0] += 1.0
        return "ok", 4

    metrics = Mock(side_effect=slow)
    monkeypatch.setattr(cf, "_metrics_for", metrics)
    result = cf.collect_tunnels(timeout=1)
    assert len(result.items) == 2
    assert result.items[1].metrics_code == "timeout"
    assert result.items[1].config_code == "timeout"
    assert metrics.call_count == 1
