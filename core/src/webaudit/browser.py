"""Rendered-page measurements with Playwright (Chromium).

Optional: without Playwright or a Chromium binary the scanner still runs and
the checks that need a browser report ``na``. Set ``WEBAUDIT_CHROMIUM_PATH``
to use a specific Chromium executable.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .config import Config
from .context import RenderData
from .egress import GuardedProxy
from .fetch import user_agent
from .netguard import BlockedTarget, NetGuard
from .protection import detect_in_title

FONTS_JS = r"""
(args) => {
  const de = document.documentElement;
  const scale = args.mobile ? Math.min(1, screen.width / Math.max(1, de.clientWidth)) : 1;
  const root = document.body || de;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let total = 0, belowMin = 0, belowSmall = 0;
  const families = {};
  const seen = new Map();
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = node.nodeValue.trim();
    if (!text) continue;
    const el = node.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName)) continue;
    let info = seen.get(el);
    if (!info) {
      if (seen.size >= args.limit * 4) break;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      info = {
        visible: cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0.05 && r.width > 1 && r.height > 1,
        size: parseFloat(cs.fontSize),
        family: (cs.fontFamily.split(',')[0] || '').replace(/["']/g, '').trim().toLowerCase(),
      };
      seen.set(el, info);
    }
    if (!info.visible) continue;
    const n = text.length;
    total += n;
    if (info.size * scale < args.minPx) belowMin += n;
    if (info.size < args.smallPx) belowSmall += n;
    families[info.family] = (families[info.family] || 0) + n;
  }
  const bodyPx = document.body ? parseFloat(getComputedStyle(document.body).fontSize) : null;
  return {total_chars: total, chars_below_min: belowMin, chars_below_small: belowSmall, families,
          scale: Math.round(scale * 1000) / 1000, body_px: bodyPx};
}
"""

# Short CSS selector for evidence ("where is the problem"); mirrors dom.css_path. Injected into snippets.
CSS_PATH_JS = r"""
  const cssPath = (el) => {
    const ident = /^-?[A-Za-z_][\w-]*$/;
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && e.tagName !== 'HTML' && parts.length < 6; e = e.parentElement) {
      const tag = e.tagName.toLowerCase();
      if (e.id && ident.test(e.id)) { parts.unshift(tag + '#' + e.id); break; }
      let part = tag;
      const cls = typeof e.className === 'string' ? e.className.trim().split(/\s+/).filter((c) => ident.test(c)).slice(0, 2) : [];
      if (cls.length) part += '.' + cls.join('.');
      const p = e.parentElement;
      if (p) {
        const same = Array.from(p.children).filter((c) => c.tagName === e.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(e) + 1})`;
      }
      parts.unshift(part);
      if (tag === 'body') break;
    }
    return parts.join(' > ');
  };
"""

CONTRAST_JS = r"""
(args) => {
  /*CSS_PATH*/
  const parse = (c) => {
    const m = (c || '').match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const blend = (top, bottom) => {
    const a = top[3];
    return [top[0] * a + bottom[0] * (1 - a), top[1] * a + bottom[1] * (1 - a), top[2] * a + bottom[2] * (1 - a), 1];
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const hex = (c) => '#' + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const background = (el) => {
    const layers = [];
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const cs = getComputedStyle(node);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;
      const bg = parse(cs.backgroundColor);
      if (bg && bg[3] > 0) { layers.push(bg); if (bg[3] >= 1) break; }
    }
    let color = [255, 255, 255, 1];
    for (let i = layers.length - 1; i >= 0; i--) color = blend(layers[i], color);
    return color;
  };
  let checked = 0, failing = 0;
  const samples = [];
  const all = document.body ? document.body.getElementsByTagName('*') : [];
  for (let i = 0; i < all.length && checked < args.limit; i++) {
    const el = all[i];
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'OPTION'].includes(el.tagName)) continue;
    let own = '';
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.nodeValue;
    if (own.trim().length < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.9) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    let fg = parse(cs.color);
    const bg = background(el);
    if (!fg || !bg) continue;
    if (fg[3] < 1) fg = blend(fg, bg);
    const l1 = lum(fg), l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const size = parseFloat(cs.fontSize), weight = parseInt(cs.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    checked++;
    if (ratio < (large ? 3 : 4.5)) {
      failing++;
      if (samples.length < 10) samples.push(`${cssPath(el)}: ${hex(fg)} on ${hex(bg)} (${ratio.toFixed(2)}:1, ${Math.round(size)}px)`);
    }
  }
  return {checked, failing, samples};
}
"""

TAP_TARGETS_JS = r"""
(args) => {
  /*CSS_PATH*/
  // Without a mobile viewport the page is zoomed out, so targets are smaller on screen.
  const scale = Math.min(1, screen.width / Math.max(1, document.documentElement.clientWidth));
  const MIN = args.min / scale;
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link]';
  const items = [];
  for (const el of Array.from(document.querySelectorAll(sel)).slice(0, args.limit)) {
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0 || cs.pointerEvents === 'none') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    items.push({el, r});
  }
  let failing = 0;
  const samples = [];
  for (let i = 0; i < items.length; i++) {
    const {el, r} = items[i];
    if (r.width >= MIN && r.height >= MIN) continue;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const ex = {left: Math.min(r.left, cx - MIN / 2), right: Math.max(r.right, cx + MIN / 2),
                top: Math.min(r.top, cy - MIN / 2), bottom: Math.max(r.bottom, cy + MIN / 2)};
    let crowded = false;
    for (let j = 0; j < items.length && !crowded; j++) {
      if (i === j) continue;
      const o = items[j];
      if (o.el.contains(el) || el.contains(o.el)) continue;
      const q = o.r;
      crowded = q.left < ex.right && q.right > ex.left && q.top < ex.bottom && q.bottom > ex.top;
    }
    if (crowded) {
      failing++;
      if (samples.length < 10) samples.push(`${cssPath(el)}: ${Math.round(r.width * scale)}×${Math.round(r.height * scale)}px on screen`);
    }
  }
  return {total: items.length, failing, samples, scale: Math.round(scale * 1000) / 1000};
}
"""

LAYOUT_JS = r"""
(tolerance) => {
  /*CSS_PATH*/
  const de = document.documentElement;
  const sw = Math.max(de.scrollWidth, document.body ? document.body.scrollWidth : 0);
  const cw = de.clientWidth;
  const wide = [];
  if (sw > cw + tolerance && document.body) {
    for (const el of document.body.getElementsByTagName('*')) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.right > cw + tolerance && getComputedStyle(el).position !== 'fixed') {
        wide.push(`${cssPath(el)}: ${Math.round(r.width)}px wide, right edge at ${Math.round(r.right)}px`);
        if (wide.length >= 5) break;
      }
    }
  }
  return {scroll_width: sw, client_width: cw, viewport_width: window.innerWidth, wide_elements: wide};
}
"""

LIBRARIES_JS = r"""
() => {
  const out = {};
  const w = window;
  const t = (fn) => { try { const v = fn(); return v ? String(v) : null; } catch (e) { return null; } };
  out.jquery = t(() => w.jQuery && w.jQuery.fn && w.jQuery.fn.jquery);
  out.jqueryui = t(() => w.jQuery && w.jQuery.ui && w.jQuery.ui.version);
  out.bootstrap = t(() => (w.bootstrap && w.bootstrap.Tooltip && w.bootstrap.Tooltip.VERSION)
      || (w.jQuery && w.jQuery.fn.tooltip && w.jQuery.fn.tooltip.Constructor && w.jQuery.fn.tooltip.Constructor.VERSION));
  out.angularjs = t(() => w.angular && w.angular.version && w.angular.version.full);
  out.lodash = t(() => w._ && typeof w._.runInContext === 'function' && w._.VERSION);
  out.moment = t(() => w.moment && w.moment.version);
  out.vue = t(() => w.Vue && w.Vue.version);
  out.mootools = t(() => w.MooTools && w.MooTools.version);
  out.prototype = t(() => w.Prototype && w.Prototype.Version);
  return out;
}
"""

IMAGES_JS = r"""
(args) => {
  /*CSS_PATH*/
  const out = [];
  for (const img of document.images) {
    const r = img.getBoundingClientRect();
    if (!img.complete || !img.naturalWidth || r.width < 2) continue;
    if (img.naturalWidth >= args.minPx && img.naturalWidth > r.width * args.ratio * (window.devicePixelRatio || 1)) {
      const src = (img.currentSrc || img.src).split('?')[0].slice(-160);
      out.push(`${src} (${cssPath(img)}): ${img.naturalWidth}px wide, shown at ${Math.round(r.width)}px`);
      if (out.length >= 10) break;
    }
  }
  return {oversized: out};
}
"""

BANNER_DETECT_JS = r"""
(markers) => {
  const area = innerWidth * innerHeight;
  if (!document.body) return false;
  for (const el of document.body.getElementsByTagName('*')) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height < area * 0.02 || r.bottom <= 0 || r.top >= innerHeight) continue;
    const text = (el.innerText || '').toLowerCase();
    if (markers.some((m) => text.includes(m))) return true;
  }
  return false;
}
"""

# When the bar cannot be closed without leaving the page, take it off the screen instead: the
# client is shown a photograph of the website, not of somebody's consent dialog.
BANNER_HIDE_JS = r"""
(markers) => {
  const area = innerWidth * innerHeight;
  if (!document.body) return 0;
  let hidden = 0;
  for (const el of Array.from(document.body.getElementsByTagName('*'))) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height < area * 0.02 || r.bottom <= 0 || r.top >= innerHeight) continue;
    const text = (el.innerText || '').toLowerCase();
    if (!markers.some((m) => text.includes(m))) continue;
    el.style.setProperty('display', 'none', 'important');
    hidden += 1;
  }
  if (hidden) {
    for (const el of [document.documentElement, document.body]) {
      el.style.setProperty('overflow', 'auto', 'important');  // bars often freeze the page behind them
    }
  }
  return hidden;
}
"""

BANNER_BUTTON_JS = r"""
(phrases) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const cands = Array.from(document.querySelectorAll('button, a, [role=button], input[type=button], input[type=submit]'));
  for (const phrase of phrases) {
    for (const el of cands) {
      const label = norm(el.innerText || el.value || el.getAttribute('aria-label'));
      if (!label || label.length > 40) continue;
      if (label !== phrase && !label.startsWith(phrase + ' ')) continue;
      const anchor = el.closest('a');
      if (anchor) {
        // A consent button wrapped in a link takes the browser somewhere else; the page we were
        // asked to measure is the one that has to stay on screen.
        const href = (anchor.getAttribute('href') || '').trim();
        if (href && !href.startsWith('#') && !/^javascript:/i.test(href)) continue;
      }
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (r.width < 1 || r.height < 1 || cs.visibility === 'hidden' || cs.display === 'none') continue;
      el.setAttribute('data-webaudit-consent', '1');
      return phrase;
    }
  }
  return null;
}
"""

CONTRAST_JS, TAP_TARGETS_JS, LAYOUT_JS, IMAGES_JS = (
    js.replace("/*CSS_PATH*/", CSS_PATH_JS.strip()) for js in (CONTRAST_JS, TAP_TARGETS_JS, LAYOUT_JS, IMAGES_JS)
)

IGNORED_CONSOLE = ("ERR_BLOCKED_BY_CLIENT", "net::ERR_ABORTED")
CONSENT_FRAME_HINTS = ("consent", "cmp", "privacy", "cookie", "gdpr")
# ... but a few frames only look like one: youtube-nocookie.com embeds are videos, and reCAPTCHA
# is not a cookie bar. Clicking inside those is how a scan ends up somewhere else entirely.
NOT_CONSENT_FRAMES = ("nocookie", "recaptcha")


def is_consent_frame(url: str) -> bool:
    low = url.lower()
    return not any(skip in low for skip in NOT_CONSENT_FRAMES) and any(hint in low for hint in CONSENT_FRAME_HINTS)


def same_page(before: str, after: str) -> bool:
    """Whether the browser is still on the page we loaded (a query or a fragment may change)."""
    a, b = urlsplit(before), urlsplit(after)
    return (a.netloc, a.path.rstrip("/")) == (b.netloc, b.path.rstrip("/"))


class BrowserUnavailable(Exception):
    pass


class Browser:
    def __init__(self, config: Config, guard: NetGuard) -> None:
        self.config = config
        self.guard = guard
        self.cfg = config.scanner["browser"]
        self._pw = None
        self._browser = None
        self._proxy = GuardedProxy(guard)

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserUnavailable("Playwright is not installed (pip install 'webaudit[browser]')") from exc
        self._pw = await async_playwright().start()
        executable = os.environ.get("WEBAUDIT_CHROMIUM_PATH") or None
        # The desktop app uses the browser that ships with Windows: WEBAUDIT_BROWSER_CHANNEL=msedge.
        channel = None if executable else (os.environ.get("WEBAUDIT_BROWSER_CHANNEL") or None)
        # All browser traffic (incl. redirects, WebSockets and loopback) goes through the
        # guarded proxy, which is the real SSRF boundary; the route handler only fails fast.
        proxy_url = await self._proxy.start()
        attempts = [channel, None] if channel else [None]  # fall back to Playwright's own Chromium
        error: Exception | None = None
        for attempt in attempts:
            try:
                self._browser = await self._pw.chromium.launch(
                    executable_path=executable,
                    channel=attempt,
                    args=["--disable-dev-shm-usage"],
                    proxy={"server": proxy_url},
                )
                return
            except Exception as exc:  # noqa: BLE001 - try the next option, then surface a readable reason
                error = exc
        await self._pw.stop()
        await self._proxy.close()
        self._pw = None
        first_line = str(error).strip().splitlines()[0] if str(error).strip() else error.__class__.__name__
        raise BrowserUnavailable(f"Chromium could not start: {first_line[:200]}") from error

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        await self._proxy.close()
        self._browser = self._pw = None

    async def _guard_route(self, route: Any) -> None:
        request = route.request
        url = request.url
        if url.startswith(("data:", "blob:")):
            await route.continue_()
            return
        try:
            await self.guard.check_url(url)
        except BlockedTarget:
            await route.abort("blockedbyclient")
            return
        if self.cfg.get("block_media") and request.resource_type == "media":
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def render(
        self,
        url: str,
        *,
        mobile: bool,
        screenshot_path: Path | None = None,
        log: Callable[[str, str], None] = lambda level, msg: None,
    ) -> RenderData:
        if self._browser is None:
            raise BrowserUnavailable("browser not started")
        limits = self.config.scanner["limits"]
        thresholds = self.config.scanner["thresholds"]
        viewport = self.cfg["mobile_viewport" if mobile else "desktop_viewport"]
        context = await self._browser.new_context(
            viewport=viewport,
            user_agent=user_agent(self.config, mobile=mobile),
            locale="sk-SK",
            is_mobile=mobile,
            has_touch=mobile,
            device_scale_factor=3 if mobile else 1,
            ignore_https_errors=True,
            service_workers="block",
        )
        await context.route("**/*", self._guard_route)
        page = await context.new_page()
        data = RenderData(ok=False)
        requests: list[Any] = []
        page.on(
            "console",
            lambda msg: (
                data.console_errors.append(msg.text) if msg.type == "error" and not any(i in msg.text for i in IGNORED_CONSOLE) else None
            ),
        )
        page.on("pageerror", lambda exc: data.console_errors.append(str(exc).splitlines()[0][:300]))
        page.on("requestfinished", lambda req: requests.append(req) if len(requests) < 400 else None)
        try:
            data.error = await self._load(page, url, log)
            if data.error:
                return data
            data.title = await page.title()
            if detect_in_title(data.title):
                data.ok = True
                data.cookie = {"challenge": True}
                return data
            here = page.url
            data.cookie = await self._dismiss_cookie_banner(page, log)
            if not same_page(here, page.url):
                # Something behind the consent button navigated away. Everything below measures the
                # page and takes its screenshot, so come back first - otherwise the report would
                # describe whatever page the click landed on.
                log("warn", f"closing the cookie bar left the page for {page.url}; going back")
                data.cookie.update(dismissed=False, left_page=True)
                data.error = await self._load(page, here, log)
                if data.error:
                    return data
            if data.cookie.get("detected") and not data.cookie.get("dismissed"):
                data.cookie["hidden"] = await self._hide_cookie_banner(page)
                if data.cookie["hidden"]:
                    log("ok", "cookie bar hidden for the screenshot")
            fonts_args = {
                "mobile": mobile,
                "minPx": thresholds["mobile_min_font_px"],
                "smallPx": thresholds["desktop_small_font_px"],
                "limit": limits["max_dom_elements_measured"],
            }
            data.metrics["fonts"] = await page.evaluate(FONTS_JS, fonts_args)
            if mobile:
                data.metrics["tap_targets"] = await page.evaluate(
                    TAP_TARGETS_JS, {"min": thresholds["tap_target_min_px"], "limit": limits["max_dom_elements_measured"]}
                )
                data.metrics["layout"] = await page.evaluate(LAYOUT_JS, thresholds["horizontal_scroll_tolerance_px"])
            else:
                data.metrics["contrast"] = await page.evaluate(CONTRAST_JS, {"limit": 400})
                data.metrics["libraries"] = await page.evaluate(LIBRARIES_JS)
                data.metrics["images"] = await page.evaluate(
                    IMAGES_JS, {"minPx": thresholds["oversized_image_min_px"], "ratio": thresholds["oversized_image_ratio"]}
                )
                data.html = await page.content()
            if screenshot_path is not None:
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(screenshot_path), type="jpeg", quality=80)
                data.screenshot = str(screenshot_path)
            if not mobile:
                narrow = self.cfg["narrow_desktop_width"]
                await page.set_viewport_size({"width": narrow, "height": viewport["height"]})
                await page.wait_for_timeout(300)
                data.metrics["narrow"] = await page.evaluate(LAYOUT_JS, thresholds["fixed_width_tolerance_px"])
            data.requests = await _request_sizes(requests)
            data.ok = True
            return data
        finally:
            await context.close()

    async def _load(self, page: Any, url: str, log: Callable[[str, str], None]) -> str | None:
        """Navigate and let the page settle. Returns a reason to give up, or ``None``."""
        try:
            await page.goto(url, wait_until="load", timeout=self.config.scanner["timeouts"]["navigation_s"] * 1000)
        except Exception as exc:  # noqa: BLE001
            if "Timeout" not in exc.__class__.__name__:
                return str(exc).splitlines()[0][:200]
            log("warn", "page kept loading past the time limit; measuring what loaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=self.cfg["network_idle_wait_ms"])
        except Exception:  # noqa: BLE001 - busy pages never go idle; that's fine
            pass
        return None

    async def _dismiss_cookie_banner(self, page: Any, log: Callable[[str, str], None]) -> dict[str, Any]:
        cfg = self.config.cookie_banners
        markers = [m.lower() for m in cfg["banner_text_markers"]]
        detected = bool(await page.evaluate(BANNER_DETECT_JS, markers))
        method = await self._click_consent(page, cfg)
        if method is None:
            for frame in page.frames[1:]:
                if is_consent_frame(frame.url):
                    method = await self._click_consent(frame, cfg)
                    if method:
                        break
        if method:
            await page.wait_for_timeout(700)
            try:  # the click may have started a navigation; know where we are before measuring
                await page.wait_for_load_state("load", timeout=self.cfg["network_idle_wait_ms"])
            except Exception:  # noqa: BLE001
                pass
            try:
                still_there = bool(await page.evaluate(BANNER_DETECT_JS, markers))
            except Exception:  # noqa: BLE001 - a navigation threw the context away; the caller checks the URL
                still_there = True
            if still_there:
                log("warn", f"cookie bar still visible after clicking ({method})")
            return {"detected": True, "dismissed": not still_there, "method": method}
        if detected:
            log("warn", "cookie bar detected but could not be closed")
        return {"detected": detected, "dismissed": False, "method": None}

    async def _hide_cookie_banner(self, page: Any) -> bool:
        """Last resort for a bar we must not click: hide it so it is not in the screenshot."""
        markers = [m.lower() for m in self.config.cookie_banners["banner_text_markers"]]
        try:
            return bool(await page.evaluate(BANNER_HIDE_JS, markers))
        except Exception:  # noqa: BLE001 - a screenshot with the bar in it is still a screenshot
            return False

    @staticmethod
    async def _click_consent(target: Any, cfg: dict[str, Any]) -> str | None:
        for selector in cfg["selectors"]:
            try:
                locator = target.locator(selector).first
                if await locator.is_visible():
                    await locator.click(timeout=2000)
                    return f"selector {selector}"
            except Exception:  # noqa: BLE001 - try the next one
                continue
        try:
            phrase = await target.evaluate(BANNER_BUTTON_JS, [p.lower() for p in cfg["phrases"]])
            if phrase:
                await target.locator("[data-webaudit-consent]").first.click(timeout=2000)
                return f"button “{phrase}”"
        except Exception:  # noqa: BLE001
            return None
        return None


async def _request_sizes(requests: list[Any]) -> list[dict[str, Any]]:
    async def one(req: Any) -> dict[str, Any]:
        size = None
        try:
            sizes = await req.sizes()
            size = sizes.get("responseBodySize", 0) + sizes.get("responseHeadersSize", 0)
        except Exception:  # noqa: BLE001
            pass
        return {"url": req.url, "type": req.resource_type, "bytes": size}

    return list(await asyncio.gather(*(one(r) for r in requests)))


def safe_filename(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.-]+", "_", re.sub(r"^https?://", "", url)).strip("_")[:80]
