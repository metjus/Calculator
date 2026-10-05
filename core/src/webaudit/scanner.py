"""Scan orchestration: gather data politely, run checks, score.

``Scanner`` is used as an async context manager and can audit many sites with
one HTTP client and one browser. Progress is reported through ``on_event`` so
that the CLI, a desktop window or the SaaS worker (server-sent events) can show
"Web 3 of 20 – kadernictvo-x.sk: taking mobile screenshot" and a live log.
A failure on one site never stops the batch.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from . import checks as check_registry
from . import pagespeed, protection, scoring, techdetect
from .browser import Browser, BrowserUnavailable, safe_filename
from .config import Config
from .context import RenderData, ScanContext
from .dom import anchors, normalize_link, parse, same_site
from .fetch import Fetch, PoliteClient, RateLimiter
from .inputs import normalize_url
from .models import LogEntry, LogLevel, ScanResult, SiteState, utcnow
from .netguard import BlockedTarget, NetGuard

PROTECTED_REASON = {
    "cloudflare": "Probably protected by Cloudflare – check manually",
}
SKIP_LINK_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".mp4", ".mp3", ".avi", ".mov")
SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml")


@dataclass
class ProgressEvent:
    index: int
    total: int
    url: str
    step: str | None = None
    level: LogLevel | None = None
    message: str | None = None
    time: datetime = field(default_factory=utcnow)
    result: ScanResult | None = None  # set on the final event of a site


EventHandler = Callable[[ProgressEvent], Awaitable[None] | None]


class Scanner:
    def __init__(
        self,
        config: Config | None = None,
        *,
        pagespeed_key: str | None = None,
        use_browser: bool = True,
        allow_private: bool = False,
        screenshots_dir: str | Path | None = None,
        limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        on_event: EventHandler | None = None,
    ) -> None:
        self.config = config or Config.load()
        self.pagespeed_key = pagespeed_key
        self.use_browser = use_browser and self.config.scanner["browser"]["enabled"]
        self.screenshots_dir = Path(screenshots_dir) if screenshots_dir else None
        self.guard = NetGuard(allow_private=allow_private)
        self.client = PoliteClient(self.config, self.guard, limiter=limiter, transport=transport)
        self.on_event = on_event
        self.browser: Browser | None = None
        self.browser_error: str | None = None

    async def __aenter__(self) -> Scanner:
        if self.use_browser:
            browser = Browser(self.config, self.guard)
            try:
                await browser.start()
                self.browser = browser
            except BrowserUnavailable as exc:
                self.browser_error = str(exc)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.browser is not None:
            await self.browser.close()
        await self.client.aclose()

    async def _emit(self, event: ProgressEvent) -> None:
        if self.on_event is None:
            return
        outcome = self.on_event(event)
        if inspect.isawaitable(outcome):
            await outcome

    # ------------------------------------------------------------------ batch

    async def scan_many(
        self,
        urls: Iterable[str],
        *,
        concurrency: int = 2,
        cancel: asyncio.Event | None = None,
    ) -> list[ScanResult]:
        items = list(urls)
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def run(index: int, url: str) -> ScanResult:
            async with semaphore:
                if cancel is not None and cancel.is_set():
                    res = ScanResult(input_url=url, state=SiteState.CANCELLED, state_reason="audit stopped")
                    res.finished_at = utcnow()
                    return res
                return await self.scan(url, index=index, total=len(items))

        return list(await asyncio.gather(*(run(i, u) for i, u in enumerate(items, start=1))))

    # ------------------------------------------------------------------- site

    async def scan(self, url: str, *, index: int = 1, total: int = 1) -> ScanResult:
        res = ScanResult(input_url=url)
        label = url

        async def log(level: str, message: str) -> None:
            entry = LogEntry(level=LogLevel(level), message=message)
            res.log.append(entry)
            await self._emit(ProgressEvent(index, total, label, level=entry.level, message=message))

        async def step(name: str) -> None:
            await self._emit(ProgressEvent(index, total, label, step=name))

        try:
            res.url = normalize_url(url)
            label = urlsplit(res.url).hostname or url
        except ValueError as exc:
            res.state, res.state_reason = SiteState.INVALID, f"Invalid URL: {exc}"
            await log("error", res.state_reason)
            return await self._finish(res, index, total, label)

        budget = self.config.scanner["timeouts"]["site_total_s"]
        try:
            await asyncio.wait_for(self._scan(res, log, step), timeout=budget + 15)
        except TimeoutError:
            if res.score is None:
                res.state, res.state_reason = SiteState.UNREACHABLE, "time limit for this website exceeded"
                await log("error", res.state_reason)
        except Exception as exc:  # noqa: BLE001 - never let one site break the batch
            res.state, res.state_reason = SiteState.UNREACHABLE, f"unexpected error: {exc.__class__.__name__}"
            await log("error", f"{res.state_reason}: {exc}")
        return await self._finish(res, index, total, label)

    async def _finish(self, res: ScanResult, index: int, total: int, label: str) -> ScanResult:
        res.finished_at = utcnow()
        await self._emit(ProgressEvent(index, total, label, step="done", result=res))
        return res

    async def _scan(self, res: ScanResult, log: Callable[..., Awaitable[None]], step: Callable[..., Awaitable[None]]) -> None:
        deadline = time.monotonic() + self.config.scanner["timeouts"]["site_total_s"]
        url = res.url
        assert url is not None

        try:
            await self.guard.check_url(url)
        except BlockedTarget as exc:
            res.state, res.state_reason = SiteState.INVALID, f"Not scanned: {exc}"
            await log("error", res.state_reason)
            return

        await step("loading homepage")
        home = await self.client.fetch(url)
        if home.status is None and not home.robots_blocked and url.startswith("https://"):
            fallback = "http://" + url[len("https://") :]
            await log("warn", f"HTTPS did not respond ({home.error}); trying HTTP")
            home = await self.client.fetch(fallback)
        if home.robots_blocked:
            res.state, res.state_reason = SiteState.DISALLOWED, "robots.txt does not allow scanning this website"
            await log("warn", res.state_reason)
            return
        if home.status is None:
            res.state, res.state_reason = SiteState.UNREACHABLE, f"Website did not load: {home.error}"
            await log("error", res.state_reason)
            return
        res.final_url = home.final_url
        found = protection.detect(home.status, home.headers, home.text, self.config.signatures)
        if found:
            self._mark_protected(res, found)
            await log("warn", f"{res.state_reason} ({', '.join(found.evidence[:2])})")
            return
        if not home.ok:
            res.state, res.state_reason = SiteState.UNREACHABLE, f"Website answered with HTTP {home.status}"
            await log("error", res.state_reason)
            return
        ctype = home.headers.get("content-type", "")
        if ctype and "html" not in ctype:
            res.state, res.state_reason = SiteState.UNREACHABLE, f"Not an HTML page ({ctype.split(';')[0]})"
            await log("error", res.state_reason)
            return
        await log("ok", f"homepage loaded (HTTP {home.status}, {home.elapsed_s or 0:.2f}s)")

        static_dom = parse(home.text)
        robots = await self.client.robots_for(home.final_url)
        ctx = ScanContext(config=self.config, url=url, home=home, dom=static_dom, static_dom=static_dom, robots=robots)

        if home.final_url.startswith("https://"):
            await step("checking http → https redirect")
            host = urlsplit(home.final_url).netloc
            ctx.http_probe = await self.client.fetch(f"http://{host}/", respect_robots=False, read_body=False)

        await step("checking sitemap, favicon and contact page")
        await self._gather_site_files(ctx)

        remaining = max(5.0, deadline - time.monotonic())
        tasks = [self._check_links(ctx, step), self._render(ctx, res, log, step)]
        if self.pagespeed_key:
            tasks.append(self._pagespeed(ctx, log, step))
        else:
            ctx.pagespeed_note = "PageSpeed skipped: no API key in settings"
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=remaining)
        except TimeoutError:
            await log("warn", "time limit reached; scoring with the data collected so far")

        if ctx.desktop and ctx.desktop.ok and ctx.desktop.cookie.get("challenge"):
            self._mark_protected(res, protection.Protection(provider="cloudflare", evidence=["browser got a challenge page"]))
            await log("warn", res.state_reason)
            return
        if ctx.browser_ok and ctx.desktop.html:
            ctx.dom = parse(ctx.desktop.html)

        await step("evaluating")
        res.tech = techdetect.detect(ctx)
        res.checks, errors = check_registry.run_all(ctx)
        for error in errors:
            await log("error", f"check crashed: {error}")
        res.score = scoring.score(res.checks, self.config.scoring)
        res.issues = scoring.rank_issues(res.checks, self.config.scoring)
        for render, name in ((ctx.desktop, "desktop"), (ctx.mobile, "mobile")):
            if render and render.screenshot:
                res.screenshots[name] = render.screenshot
        if res.score is None:
            res.state, res.state_reason = SiteState.UNREACHABLE, "nothing could be evaluated"
            await log("error", res.state_reason)
            return
        res.state = SiteState.OK
        await log("ok", f"score {res.score.total}/100 ({res.score.category.value}), {len(res.issues)} issues")

    def _mark_protected(self, res: ScanResult, found: protection.Protection) -> None:
        res.protection = found
        res.state = SiteState.PROTECTED
        res.state_reason = PROTECTED_REASON.get(found.provider, f"Probably protected by {found.provider} – check manually")

    async def _gather_site_files(self, ctx: ScanContext) -> None:
        base = ctx.final_url
        origin = PoliteClient.origin(base)
        sitemap_candidates = [s for s in ctx.robots.sitemaps if same_site(s, base)][:2] or [origin + p for p in SITEMAP_PATHS]
        ctx.sitemap_found = False
        for candidate in sitemap_candidates:
            got = await self.client.fetch(candidate, max_bytes=200_000)
            if got.ok and ("<urlset" in got.text or "<sitemapindex" in got.text):
                ctx.sitemap_found = True
                break

        icon = ctx.static_dom.find("link", rel=lambda r: r and any("icon" in v.lower() for v in (r if isinstance(r, list) else [r])))
        if icon is not None and icon.get("href"):
            ctx.favicon_found = True
        else:
            got = await self.client.fetch(origin + "/favicon.ico", read_body=False)
            ctx.favicon_found = got.ok and "html" not in got.headers.get("content-type", "")

        from .checks.trust import find_contact_link

        contact_url = find_contact_link(ctx.static_dom, base, self.config.signatures["contact_link_keywords"])
        if contact_url and contact_url.rstrip("/") != base.rstrip("/"):
            got = await self.client.fetch(contact_url)
            if got.ok and "html" in got.headers.get("content-type", "html"):
                ctx.contact_dom = parse(got.text)
                ctx.link_results[contact_url] = (got.status, None)

    async def _check_links(self, ctx: ScanContext, step: Callable[..., Awaitable[None]]) -> None:
        limits = self.config.scanner["limits"]
        base = ctx.final_url
        internal: list[str] = []
        for a in anchors(ctx.static_dom):
            link = normalize_link(a["href"], base)
            if not link or not same_site(link, base) or link in internal or link in ctx.link_results:
                continue
            if link.rstrip("/") == base.rstrip("/") or urlsplit(link).path.lower().endswith(SKIP_LINK_EXTENSIONS):
                continue
            internal.append(link)
        from .checks.trust import social_profiles

        external = [u for u in social_profiles(ctx) if urlsplit(u).path not in ("", "/")]
        targets = internal[: limits["max_internal_links_checked"]] + external[: limits["max_external_links_checked"]]
        if not targets:
            return
        await step(f"checking {len(targets)} links")

        async def one(link: str) -> None:
            ctx.link_results[link] = await self.client.check_link(link)

        await asyncio.gather(*(one(link) for link in targets))

    async def _render(
        self, ctx: ScanContext, res: ScanResult, log: Callable[..., Awaitable[None]], step: Callable[..., Awaitable[None]]
    ) -> None:
        if self.browser is None:
            reason = self.browser_error or "browser disabled"
            await log("warn", f"browser checks skipped: {reason}")
            await self._image_sizes_without_browser(ctx)
            return

        def sync_log(level: str, message: str) -> None:
            res.log.append(LogEntry(level=LogLevel(level), message=message))

        for mobile in (False, True):
            name = "mobile" if mobile else "desktop"
            await step(f"rendering {name} view" + (" and taking screenshot" if self.screenshots_dir else ""))
            shot = None
            if self.screenshots_dir is not None:
                shot = self.screenshots_dir / f"{safe_filename(ctx.final_url)}-{name}.jpg"
            try:
                render = await self.browser.render(ctx.final_url, mobile=mobile, screenshot_path=shot, log=sync_log)
            except Exception as exc:  # noqa: BLE001
                render = RenderData(ok=False, error=f"{exc.__class__.__name__}: {str(exc)[:160]}")
            if mobile:
                ctx.mobile = render
            else:
                ctx.desktop = render
            if render.ok:
                if render.cookie.get("challenge"):
                    return
                if render.cookie.get("dismissed"):
                    await log("ok", f"{name}: cookie bar closed ({render.cookie.get('method')})")
                await log("ok", f"{name} view measured")
            else:
                await log("warn", f"{name} view failed: {render.error}")

    async def _image_sizes_without_browser(self, ctx: ScanContext) -> None:
        limit = self.config.scanner["limits"]["max_images_checked_without_browser"]
        sources: list[str] = []
        for img in ctx.static_dom.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src and not str(src).startswith("data:"):
                absolute = urljoin(ctx.final_url, str(src))
                if absolute not in sources:
                    sources.append(absolute)
        for src in sources[:limit]:
            got: Fetch = await self.client.fetch(src, method="HEAD", read_body=False, verify=False)
            length = got.headers.get("content-length")
            if got.ok and length and length.isdigit():
                ctx.image_bytes[src] = int(length)

    async def _pagespeed(self, ctx: ScanContext, log: Callable[..., Awaitable[None]], step: Callable[..., Awaitable[None]]) -> None:
        await step("running Google PageSpeed (mobile + desktop)")
        timeout = self.config.scanner["timeouts"]["pagespeed_s"]
        results = await asyncio.gather(
            *(pagespeed.run(ctx.final_url, s, self.pagespeed_key or "", timeout) for s in ("mobile", "desktop")),
            return_exceptions=True,
        )
        for strategy, outcome in zip(("mobile", "desktop"), results, strict=True):
            if isinstance(outcome, BaseException):
                ctx.pagespeed_note = (
                    str(outcome) if isinstance(outcome, pagespeed.PageSpeedError) else f"PageSpeed failed: {outcome.__class__.__name__}"
                )
                await log("warn", f"PageSpeed {strategy}: {ctx.pagespeed_note}")
            else:
                ctx.pagespeed[strategy] = outcome
        if ctx.pagespeed:
            await log("ok", "PageSpeed results received")


async def scan_url(url: str, **kwargs: Any) -> ScanResult:
    """Convenience wrapper for a single site."""
    async with Scanner(**kwargs) as scanner:
        return await scanner.scan(url)
