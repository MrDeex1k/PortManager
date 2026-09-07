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
    opener = Mock()
    opener.open.return_value = response
    builder = Mock(return_value=opener)
    monkeypatch.setattr(cf, "build_opener", builder)
    assert cf.read_metrics("::1", 20241, timeout=0.5) == 4
    opener.open.assert_called_once_with("http://[::1]:20241/metrics", timeout=0.5)
    assert builder.call_args.args[0].proxies == {}
    assert (
        builder.call_args.args[1].redirect_request(None, None, 302, None, None, None)
        is None
    )
    response.read.assert_called_once_with(1024 * 1024 + 1)
    response.__exit__.assert_called_once()


@pytest.mark.parametrize("host", ["localhost", "example.com", "192.168.1.2", "0.0.0.0"])
def test_non_loopback_metrics_never_open_http(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    builder = Mock()
    monkeypatch.setattr(cf, "build_opener", builder)
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
    result = cf._metrics_for(connector, timeout=3.0)
    assert result == (("ok", 4) if succeed else ("error", None))
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
