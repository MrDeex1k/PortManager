"""Prawdziwy HTTP loopback, bez uruchamiania ani zmieniania tunelu."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError

import pytest

from portscanner.core.cloudflared import read_metrics


@pytest.mark.parametrize("redirect", [False, True])
def test_loopback_metrics_transport(redirect: bool) -> None:
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            paths.append(self.path)
            if redirect:
                self.send_response(302)
                self.send_header("Location", "/must-not-follow")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"cloudflared_tunnel_ha_connections 4\n")

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            if redirect:
                with pytest.raises(HTTPError):
                    read_metrics("127.0.0.1", server.server_port)
            else:
                assert read_metrics("127.0.0.1", server.server_port) == 4
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert paths == ["/metrics"]
