"""Serve the fixture websites for manual CLI runs (no internet needed).

    python tests/serve_fixtures.py /tmp/fixtures
    SSL_CERT_FILE=/tmp/fixtures/ca.pem webaudit scan --allow-private $(cat /tmp/fixtures/urls.txt)

Writes ``ca.pem`` (trust anchor for the HTTPS fixture) and ``urls.txt`` into
the given folder, then serves until interrupted.
"""

from __future__ import annotations

import ssl
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import trustme  # noqa: E402
from conftest import FixtureServers  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures-out")
    out.mkdir(parents=True, exist_ok=True)
    ca = trustme.CA()
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert("127.0.0.1").configure_cert(server_ctx)
    ca.cert_pem.write_to_path(str(out / "ca.pem"))
    servers = FixtureServers()
    servers.start("modern", "127.0.0.1", tls_context=server_ctx)
    servers.start("legacy", "127.0.0.2")
    servers.start("cloudflare", "127.0.0.3")
    servers.start("robots", "127.0.0.4")
    (out / "urls.txt").write_text("\n".join(servers.urls.values()) + "\n", "utf-8")
    for name, url in servers.urls.items():
        print(f"{name:11} {url}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        servers.stop()


if __name__ == "__main__":
    main()
