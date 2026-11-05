"""Exercise real kubectl against a temporary loopback API, never a live cluster."""

import json
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from portscanner.core import kube_command
from portscanner.core.kube import collect_nodeports
from portscanner.core.model import LocalIP


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="Requires kubectl CLI")
def test_real_kubectl_projects_resources_and_retains_context(tmp_path, monkeypatch):
    """Large unused API fields must not consume the subprocess output budget."""
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "web", "namespace": "demo"},
        "spec": {
            "type": "NodePort",
            "ports": [{"port": 80, "nodePort": 31080, "protocol": "TCP"}],
        },
    }
    node = {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {"name": "local", "annotations": {"unused": "x" * 65536}},
        "status": {
            "addresses": [{"type": "InternalIP", "address": "192.0.2.1"}],
            "images": ["x" * 65536],
        },
    }
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            paths.append(path)
            payload = {
                "/api": {"kind": "APIVersions", "versions": ["v1"]},
                "/apis": {"kind": "APIGroupList", "groups": []},
                "/api/v1": {
                    "kind": "APIResourceList",
                    "groupVersion": "v1",
                    "resources": [
                        {
                            "name": "services",
                            "namespaced": True,
                            "kind": "Service",
                            "verbs": ["list"],
                        },
                        {
                            "name": "nodes",
                            "namespaced": False,
                            "kind": "Node",
                            "verbs": ["list"],
                        },
                    ],
                },
                "/api/v1/services": {
                    "kind": "ServiceList",
                    "apiVersion": "v1",
                    "items": [service],
                },
                "/api/v1/nodes": {
                    "kind": "NodeList",
                    "apiVersion": "v1",
                    "items": [node],
                },
            }.get(path)
            self.send_response(200 if payload is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload or {}).encode())

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        config = tmp_path / "kubeconfig"
        config.write_text(
            json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Config",
                    "current-context": "audit-local",
                    "contexts": [
                        {"name": "audit-local", "context": {"cluster": "fake"}}
                    ],
                    "clusters": [
                        {
                            "name": "fake",
                            "cluster": {
                                "server": f"http://127.0.0.1:{server.server_port}"
                            },
                        }
                    ],
                }
            )
        )
        monkeypatch.setenv("KUBECONFIG", str(config))
        monkeypatch.setattr(kube_command, "OUTPUT_LIMIT", 1024)
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            result = collect_nodeports(
                (LocalIP("test", "192.0.2.1", "ipv4"),), timeout=5
            )
            assert result.report.status == "ok", result.report
            assert result.items[0].port == 31080
            assert result.items[0].kubernetes[0].context == "audit-local"
            assert "/api/v1/services" in paths and "/api/v1/nodes" in paths
        finally:
            server.shutdown()
            thread.join(timeout=2)
