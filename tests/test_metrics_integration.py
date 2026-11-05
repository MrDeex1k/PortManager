"""Prawdziwy HTTP loopback, bez uruchamiania ani zmieniania tunelu."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
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


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_slow_trickle_obeys_total_http_deadline(phase):
    """Repeated small writes cannot extend the metrics request beyond its budget."""
    import time

    stop = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if phase == "headers":
                    for part in [b"HTTP/1.1 200 OK\r\n", b"X-Test: a\r\n"] * 20:
                        self.wfile.write(part)
                        self.wfile.flush()
                        if stop.wait(0.04):
                            return
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "1000")
                    self.end_headers()
                    for _ in range(100):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        if stop.wait(0.04):
                            return
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            start = time.monotonic()
            with pytest.raises(TimeoutError):
                read_metrics("127.0.0.1", server.server_port, timeout=0.15)
            assert time.monotonic() - start < 0.7
        finally:
            stop.set()
            server.shutdown()
            thread.join(timeout=2)
