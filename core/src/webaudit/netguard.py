"""Outbound target validation (SSRF protection).

In the SaaS the scanner runs inside our infrastructure and fetches URLs typed by
customers, so it must never reach loopback, private networks or cloud metadata
endpoints. ``check_url`` validates URLs before the HTTP client requests them
(every redirect hop); ``resolve`` is used by the browser's egress proxy
(``egress.py``), which connects to the very address it validated, so the
browser cannot be steered by redirects, WebSockets or DNS rebinding. Production
deployments should still block private ranges at the network level as well.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit


class BlockedTarget(Exception):
    """Raised for URLs the scanner refuses to fetch."""


ALLOWED_SCHEMES = {"http", "https"}


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _is_local_name(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    return lowered == "localhost" or lowered.endswith((".localhost", ".local", ".internal"))


class NetGuard:
    def __init__(self, allow_private: bool = False, is_public: Callable[[str], bool] = is_public_ip) -> None:
        self.allow_private = allow_private
        self._is_public = is_public
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

    async def resolve(self, host: str, port: int) -> str:
        """Resolve ``host`` once and return the address to connect to.

        Raises BlockedTarget when any address is not public (unless private
        targets are allowed) and OSError when the name does not resolve.
        """
        try:
            ipaddress.ip_address(host.split("%", 1)[0])
            addresses = [host]
        except ValueError:
            if _is_local_name(host) and not self.allow_private:
                raise BlockedTarget(f"{host} is a local name") from None
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(info[4][0] for info in infos))
        if not self.allow_private and not all(self._is_public(a) for a in addresses):
            raise BlockedTarget(f"{host} resolves to a private or reserved address")
        return addresses[0]

    async def _resolve_is_public(self, host: str) -> bool:
        try:
            ipaddress.ip_address(host.split("%", 1)[0])
        except ValueError:
            pass  # not an IP literal, resolve it
        else:
            return self._is_public(host)
        if _is_local_name(host):
            return False
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            # Unresolvable here; the HTTP client will report it as unreachable.
            # Behind an egress proxy DNS happens upstream, which also enforces policy.
            return True
        return all(self._is_public(info[4][0]) for info in infos)
