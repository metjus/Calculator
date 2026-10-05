"""Polite HTTP client: robots.txt, per-host pacing, guarded redirects, size caps."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import UnicodeDammit

from . import __version__
from .config import Config
from .netguard import BlockedTarget, NetGuard
from .robots import Robots

REDIRECT_CODES = {301, 302, 303, 307, 308}


@dataclass
class TlsInfo:
    valid: bool
    error: str | None = None
    not_after: datetime | None = None
    days_left: int | None = None
    issuer: str | None = None


@dataclass
class Fetch:
    url: str
    final_url: str
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    content: bytes = b""
    redirects: list[tuple[str, int]] = field(default_factory=list)
    error: str | None = None
    tls: TlsInfo | None = None
    elapsed_s: float | None = None
    robots_blocked: bool = False
    _text: str | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def text(self) -> str:
        if self._text is None:
            charset = None
            ctype = self.headers.get("content-type", "")
            if "charset=" in ctype:
                charset = ctype.split("charset=", 1)[1].split(";")[0].strip().strip("\"'")
            dammit = UnicodeDammit(self.content, known_definite_encodings=[charset] if charset else [])
            self._text = dammit.unicode_markup or ""
        return self._text


class RateLimiter(Protocol):
    async def wait(self, host: str) -> None: ...
    def set_min_delay(self, host: str, delay: float) -> None: ...


class HostRateLimiter:
    """One request at a time per host, at least ``min_delay`` seconds apart.

    In-process only; the SaaS worker pool injects a shared (database-backed)
    limiter so that politeness holds across all workers and tenants.
    """

    def __init__(self, min_delay: float) -> None:
        self.min_delay = min_delay
        self._delays: dict[str, float] = {}
        self._next: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_min_delay(self, host: str, delay: float) -> None:
        self._delays[host] = max(self.min_delay, delay)

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            pause = self._next.get(host, 0.0) - time.monotonic()
            if pause > 0:
                await asyncio.sleep(pause)
            self._next[host] = time.monotonic() + self._delays.get(host, self.min_delay)


def user_agent(config: Config, mobile: bool = False) -> str:
    token = f"{config.scanner['user_agent_token']}/{__version__} (+{config.scanner['user_agent_info_url']})"
    if mobile:
        base = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36"
    else:
        base = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    return f"{base} {token}"


def _describe_tls_error(message: str) -> str:
    lowered = message.lower()
    if "expired" in lowered:
        return "certificate expired"
    if "hostname mismatch" in lowered or "doesn't match" in lowered or "not valid for" in lowered:
        return "certificate issued for a different domain"
    if "self-signed" in lowered or "self signed" in lowered:
        return "self-signed certificate"
    if "unable to get local issuer" in lowered:
        return "incomplete certificate chain or untrusted issuer"
    return "certificate could not be verified"


def _is_tls_error(exc: Exception) -> bool:
    text = f"{exc} {exc.__cause__ or ''}".lower()
    return "certificate" in text or "ssl" in text or "tls" in text


def _tls_from_response(response: httpx.Response) -> TlsInfo | None:
    stream = response.extensions.get("network_stream")
    ssl_object = stream.get_extra_info("ssl_object") if stream is not None else None
    if ssl_object is None:
        return None
    try:
        cert = ssl_object.getpeercert()
    except ValueError:
        cert = None
    if not cert:
        return TlsInfo(valid=True)
    not_after = None
    days_left = None
    if cert.get("notAfter"):
        import ssl

        not_after = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), tz=UTC)
        days_left = (not_after - datetime.now(UTC)).days
    issuer = None
    for rdn in cert.get("issuer", ()):
        for key, value in rdn:
            if key in ("organizationName", "commonName") and issuer is None:
                issuer = value
    return TlsInfo(valid=True, not_after=not_after, days_left=days_left, issuer=issuer)


class PoliteClient:
    def __init__(
        self,
        config: Config,
        guard: NetGuard,
        limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.guard = guard
        self.agent_token = config.scanner["user_agent_token"]
        politeness = config.scanner["politeness"]
        self.limiter = limiter or HostRateLimiter(politeness["min_delay_between_requests_s"])
        self.max_crawl_delay = politeness["max_crawl_delay_s"]
        self.robots_5xx_disallow = politeness["robots_5xx_policy"] == "disallow"
        limits = config.scanner["limits"]
        self.max_redirects = limits["max_redirects"]
        self.max_bytes = limits["max_html_bytes"]
        headers = {
            "User-Agent": user_agent(config),
            "Accept-Language": config.scanner["accept_language"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        timeout = httpx.Timeout(config.scanner["timeouts"]["request_s"])
        kwargs = dict(headers=headers, timeout=timeout, follow_redirects=False)
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.AsyncClient(verify=True, **kwargs)
        self._insecure = httpx.AsyncClient(verify=False, **kwargs)
        self._robots: dict[str, Robots] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._insecure.aclose()

    @staticmethod
    def origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    async def robots_for(self, url: str) -> Robots:
        origin = self.origin(url)
        lock = self._robots_locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self._robots:
                self._robots[origin] = await self._load_robots(origin)
            return self._robots[origin]

    async def _load_robots(self, origin: str) -> Robots:
        result = await self.fetch(f"{origin}/robots.txt", respect_robots=False, max_bytes=500_000, verify=False)
        if result.status is None:
            robots = Robots.allow_all()  # unreachable host: the page fetch will report it
        elif result.status >= 500:
            robots = Robots(disallow_all=self.robots_5xx_disallow)
        elif result.ok and "html" not in result.headers.get("content-type", ""):
            robots = Robots(result.text)
        else:
            robots = Robots.allow_all()
        delay = robots.crawl_delay(self.agent_token)
        if delay:
            self.limiter.set_min_delay(urlsplit(origin).hostname or "", min(delay, self.max_crawl_delay))
        return robots

    async def allowed(self, url: str) -> bool:
        robots = await self.robots_for(url)
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return robots.can_fetch(self.agent_token, path)

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        respect_robots: bool = True,
        max_bytes: int | None = None,
        verify: bool = True,
        read_body: bool = True,
    ) -> Fetch:
        """Fetch ``url`` following redirects manually so every hop is validated."""
        result = Fetch(url=url, final_url=url)
        current = url
        cap = self.max_bytes if max_bytes is None else max_bytes
        for _hop in range(self.max_redirects + 1):
            try:
                await self.guard.check_url(current)
            except BlockedTarget as exc:
                result.error = f"blocked target: {exc}"
                return result
            if respect_robots and not await self.allowed(current):
                result.robots_blocked = True
                result.error = "disallowed by robots.txt"
                return result
            host = urlsplit(current).hostname or ""
            await self.limiter.wait(host)
            client = self._client if verify else self._insecure
            started = time.monotonic()
            try:
                async with client.stream(method, current) as response:
                    result.elapsed_s = time.monotonic() - started
                    result.status = response.status_code
                    result.headers = {k.lower(): v for k, v in response.headers.multi_items()}
                    result.final_url = str(response.url)
                    if current.startswith("https://"):
                        result.tls = _tls_from_response(response) or (TlsInfo(valid=True) if verify else None)
                    location = response.headers.get("location")
                    if response.status_code in REDIRECT_CODES and location:
                        result.redirects.append((current, response.status_code))
                        current = urljoin(current, location)
                        continue
                    if read_body and method != "HEAD":
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            chunks.append(chunk)
                            size += len(chunk)
                            if size >= cap:
                                break
                        result.content = b"".join(chunks)[:cap]
                    return result
            except httpx.HTTPError as exc:
                if verify and current.startswith("https://") and _is_tls_error(exc):
                    # Record the certificate problem, then keep auditing the content.
                    tls_error = _describe_tls_error(str(exc.__cause__ or exc))
                    retry = await self.fetch(
                        current,
                        method=method,
                        respect_robots=respect_robots,
                        max_bytes=max_bytes,
                        verify=False,
                        read_body=read_body,
                    )
                    retry.url = url
                    retry.redirects = result.redirects + retry.redirects
                    retry.tls = TlsInfo(valid=False, error=tls_error)
                    return retry
                result.error = _describe_http_error(exc)
                result.final_url = current
                return result
        result.error = "too many redirects"
        return result

    async def check_link(self, url: str) -> tuple[int | None, str | None]:
        """Lightweight existence check: HEAD, falling back to a GET without body."""
        head = await self.fetch(url, method="HEAD", read_body=False, verify=False)
        if head.robots_blocked:
            return None, "robots"
        if head.status in (405, 501, 403, 400) or (head.status is None and head.error and "blocked" not in head.error):
            get = await self.fetch(url, method="GET", read_body=False, verify=False)
            return get.status, get.error
        return head.status, head.error


def _describe_http_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timed out"
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if "name or service not known" in lowered or "nodename nor servname" in lowered or "getaddrinfo" in lowered:
        return "domain does not resolve (DNS)"
    if "connection refused" in lowered or "all connection attempts failed" in lowered:
        return "server is not responding (connection failed)"
    return text[:200]
