"""Outbound target validation (SSRF protection).

In the SaaS the scanner runs inside our infrastructure and fetches URLs typed by
customers, so it must never reach loopback, private networks or cloud metadata
endpoints. This module is the in-process guard; production deployments should
additionally route scanner egress through a proxy that enforces the same rule
(this guard cannot fully prevent DNS rebinding on its own).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class BlockedTarget(Exception):
    """Raised for URLs the scanner refuses to fetch."""


ALLOWED_SCHEMES = {"http", "https"}


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class NetGuard:
    def __init__(self, allow_private: bool = False) -> None:
        self.allow_private = allow_private
        self._cache: dict[str, bool] = {}

    async def check_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ALLOWED_SCHEMES:
            raise BlockedTarget(f"unsupported scheme: {parts.scheme or '(none)'}")
        host = parts.hostname
        if not host:
            raise BlockedTarget("URL has no host")
        if parts.username or parts.password:
            raise BlockedTarget("URLs with credentials are not scanned")
        if self.allow_private:
            return
        await self.check_host(host)

    async def check_host(self, host: str) -> None:
        if self.allow_private:
            return
        cached = self._cache.get(host)
        if cached is None:
            cached = await self._resolve_is_public(host)
            self._cache[host] = cached
        if not cached:
            raise BlockedTarget(f"{host} resolves to a private or reserved address")

    async def _resolve_is_public(self, host: str) -> bool:
        try:
            return is_public_ip(host)
        except ValueError:
            pass  # not an IP literal, resolve it
        lowered = host.lower().rstrip(".")
        if lowered == "localhost" or lowered.endswith((".localhost", ".local", ".internal")):
            return False
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            # Unresolvable here; the HTTP client will report it as unreachable.
            # Behind an egress proxy DNS happens upstream, which also enforces policy.
            return True
        return all(is_public_ip(info[4][0]) for info in infos)
