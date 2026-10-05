"""Guarded egress proxy for the headless browser.

Playwright's route handlers do not see redirect hops or WebSocket handshakes,
and Chromium resolves DNS itself, so URL checks alone cannot keep a hostile
page away from internal addresses. Chromium is therefore pointed at this tiny
in-process HTTP proxy: for every connection it resolves the host once through
``NetGuard.resolve`` (which refuses loopback, private, link-local and other
reserved addresses) and connects to exactly that address. HTTPS and WebSocket
traffic arrives as ``CONNECT`` tunnels; plain-HTTP requests are forwarded one
per connection (``Connection: close``).
"""

from __future__ import annotations

import asyncio
import contextlib
from urllib.parse import urlsplit

from .netguard import BlockedTarget, NetGuard

MAX_HEAD_BYTES = 64 * 1024
HOP_BY_HOP = {"proxy-connection", "proxy-authorization", "connection", "keep-alive"}


def _split_host_port(authority: str, default_port: int) -> tuple[str, int]:
    if authority.startswith("["):  # [IPv6]:port
        host, _, rest = authority[1:].partition("]")
        port = rest.lstrip(":")
    elif authority.count(":") == 1:
        host, _, port = authority.partition(":")
    else:
        host, port = authority, ""
    return host, int(port) if port else default_port


class GuardedProxy:
    def __init__(self, guard: NetGuard, connect_timeout: float = 15.0) -> None:
        self.guard = guard
        self.connect_timeout = connect_timeout
        self.blocked: list[str] = []  # hosts refused during this proxy's lifetime
        self._server: asyncio.base_events.Server | None = None

    @property
    def url(self) -> str:
        assert self._server is not None, "proxy not started"
        host, port = self._server.sockets[0].getsockname()[:2]
        return f"http://{host}:{port}"

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.url

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None

    async def _open(self, host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        address = await self.guard.resolve(host, port)
        return await asyncio.wait_for(asyncio.open_connection(address, port), self.connect_timeout)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self.connect_timeout)
            if len(head) > MAX_HEAD_BYTES:
                raise ValueError("request head too large")
            request_line, *header_lines = head.decode("latin-1").split("\r\n")
            method, target, version = request_line.split(" ", 2)
            if method.upper() == "CONNECT":
                host, port = _split_host_port(target, 443)
                upstream_reader, upstream_writer = await self._open(host, port)
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
            else:
                parts = urlsplit(target)
                if parts.scheme != "http" or not parts.hostname:
                    raise ValueError("only absolute http:// URLs can be proxied")
                upstream_reader, upstream_writer = await self._open(parts.hostname, parts.port or 80)
                path = parts.path or "/"
                if parts.query:
                    path += "?" + parts.query
                headers = [h for h in header_lines if h and h.split(":", 1)[0].strip().lower() not in HOP_BY_HOP]
                upstream_writer.write(f"{method} {path} {version}\r\n".encode("latin-1"))
                upstream_writer.write(("\r\n".join([*headers, "Connection: close"]) + "\r\n\r\n").encode("latin-1"))
                await upstream_writer.drain()
            await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer))
        except BlockedTarget as exc:
            self.blocked.append(str(exc))
            await _reply(writer, b"403 Forbidden")
        except (OSError, TimeoutError):
            await _reply(writer, b"502 Bad Gateway")
        except (ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            await _reply(writer, b"400 Bad Request")
        finally:
            for w in (writer, upstream_writer):
                if w is not None:
                    with contextlib.suppress(Exception):
                        w.close()


async def _reply(writer: asyncio.StreamWriter, status: bytes) -> None:
    with contextlib.suppress(Exception):
        writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (OSError, asyncio.IncompleteReadError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()
