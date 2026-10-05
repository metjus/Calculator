from __future__ import annotations

import os
import shutil
import ssl
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from sites import SITES

# The container ships Chromium outside Playwright's default location.
if "WEBAUDIT_CHROMIUM_PATH" not in os.environ and Path("/opt/pw-browsers/chromium").exists():
    os.environ["WEBAUDIT_CHROMIUM_PATH"] = "/opt/pw-browsers/chromium"


def _handler_for(routes: dict, ref: dict) -> type[BaseHTTPRequestHandler]:
    def fill(text: str) -> str:
        for key, value in {"{origin}": ref["origin"], **ref["shared"]}.items():
            text = text.replace(key, value)
        return text

    class Handler(BaseHTTPRequestHandler):
        def _respond(self, with_body: bool) -> None:
            ref["hits"].append(self.path)
            path = self.path.split("?", 1)[0]
            status, headers, body = routes.get(path, (404, {"Content-Type": "text/html"}, "<h1>Not found</h1>"))
            if isinstance(body, str):
                body = fill(body).encode("utf-8")
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, fill(value))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if with_body:
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            self._respond(True)

        def do_HEAD(self) -> None:  # noqa: N802
            self._respond(False)

        def log_message(self, *args: object) -> None:
            pass

    return Handler


class FixtureServers:
    def __init__(self) -> None:
        self.urls: dict[str, str] = {}
        self.hits: dict[str, list[str]] = {}  # request paths each site received
        self.placeholders: dict[str, str] = {}  # shared {name} -> value substitutions
        self.servers: list[ThreadingHTTPServer] = []
        self.ca = None

    def start(self, name: str, host: str, tls_context: ssl.SSLContext | None = None) -> str:
        origin_ref = {"origin": "", "hits": [], "shared": self.placeholders}
        self.hits[name] = origin_ref["hits"]
        server = ThreadingHTTPServer((host, 0), _handler_for(SITES[name], origin_ref))
        scheme = "http"
        if tls_context is not None:
            server.socket = tls_context.wrap_socket(server.socket, server_side=True)
            scheme = "https"
        origin = f"{scheme}://{host}:{server.server_address[1]}"
        origin_ref["origin"] = origin
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        self.urls[name] = origin + "/"
        return self.urls[name]

    def stop(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()


@pytest.fixture(scope="session")
def sites() -> Iterator[FixtureServers]:
    import trustme

    servers = FixtureServers()
    ca = trustme.CA()
    cert = ca.issue_cert("127.0.0.1")
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    cert.configure_cert(server_ctx)
    servers.ca = ca
    servers.start("modern", "127.0.0.1", tls_context=server_ctx)
    servers.start("legacy", "127.0.0.2")
    servers.start("cloudflare", "127.0.0.3")
    servers.start("robots", "127.0.0.4")
    internal = servers.start("internal", "127.0.0.6").rstrip("/")
    servers.placeholders.update({"{internal}": internal, "{internal_hostport}": internal.split("//", 1)[1]})
    servers.start("attacker", "127.0.0.5")
    yield servers
    servers.stop()


@pytest.fixture(scope="session")
def trusted_transport(sites: FixtureServers) -> httpx.AsyncHTTPTransport:
    """Transport that trusts the fixture CA (and nothing is proxied)."""
    ctx = ssl.create_default_context()
    sites.ca.configure_trust(ctx)
    return httpx.AsyncHTTPTransport(verify=ctx)


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)


def chromium_available() -> bool:
    path = os.environ.get("WEBAUDIT_CHROMIUM_PATH")
    if path:
        return Path(path).exists()
    return shutil.which("chromium") is not None


needs_browser = pytest.mark.skipif(not chromium_available(), reason="Chromium not available")
