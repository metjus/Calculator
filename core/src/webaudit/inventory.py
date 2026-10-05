"""What the homepage contains, as structured data (for the Claude Code export).

Built from the ``ScanContext`` after the checks ran; pure, no I/O. All page
text goes through ``redact_text`` so the inventory never holds e-mail
addresses or phone numbers. Lists are capped to keep stored results small.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from .context import ScanContext
from .dom import NON_CONTENT_TAGS, css_path, json_ld_types, meta_content, normalize_link, same_site, visible_text
from .redact import redact_text

BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "figcaption", "address", "dt", "dd", "td", "th", "label")
HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
MAX_BLOCKS = 250
MAX_TEXT_CHARS = 15_000
MAX_LINKS = 120
MAX_IMAGES = 80
MAX_ASSETS = 60
FIELD_TYPES_SKIPPED = {"hidden"}


def _text(node: Tag, limit: int = 300) -> str:
    return redact_text(" ".join(node.get_text(" ", strip=True).split()))[:limit]


def _attr(tag: Tag, name: str) -> str | None:
    value = tag.get(name)
    if isinstance(value, list):
        value = " ".join(value)
    return str(value).strip() if value is not None else None


def _meta(dom: BeautifulSoup, static: BeautifulSoup) -> dict[str, Any]:
    def first(**kwargs: str) -> str | None:
        value = meta_content(dom, **kwargs) or meta_content(static, **kwargs)
        return redact_text(value) if value else value

    canonical = dom.find("link", rel=lambda r: r and "canonical" in r) or static.find("link", rel=lambda r: r and "canonical" in r)
    html = dom.find("html") or static.find("html")
    title = dom.find("title") or static.find("title")
    return {
        "title": redact_text(" ".join(title.get_text().split())) if title else None,
        "lang": _attr(html, "lang") if html else None,
        "description": first(name="description"),
        "viewport": first(name="viewport"),
        "robots": first(name="robots"),
        "generator": first(name="generator"),
        "canonical": _attr(canonical, "href") if canonical else None,
        "og_title": first(prop="og:title"),
        "og_description": first(prop="og:description"),
        "og_image": first(prop="og:image"),
    }


def _content_blocks(dom: BeautifulSoup) -> list[dict[str, str]]:
    body = dom.find("body") or dom
    blocks: list[dict[str, str]] = []
    total = 0
    for tag in body.find_all(BLOCK_TAGS):
        if any(isinstance(p, Tag) and (p.name in BLOCK_TAGS or p.name in NON_CONTENT_TAGS) for p in tag.parents):
            continue  # nested block (li > p) or hidden content; the outer block already has the text
        text = _text(tag, 600)
        if not text:
            continue
        blocks.append({"tag": tag.name, "text": text})
        total += len(text)
        if len(blocks) >= MAX_BLOCKS or total >= MAX_TEXT_CHARS:
            break
    return blocks


def _navigation(dom: BeautifulSoup, base: str) -> list[dict[str, str]]:
    containers = dom.find_all("nav") or dom.find_all("header")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for container in containers:
        for a in container.find_all("a", href=True):
            link = normalize_link(a["href"], base)
            if not link or link in seen:
                continue
            seen.add(link)
            out.append({"text": _text(a, 80), "href": redact_text(link)})
    return out[:40]


def _links(ctx: ScanContext) -> dict[str, Any]:
    internal: list[dict[str, Any]] = []
    external: list[dict[str, Any]] = []
    seen: set[str] = set()
    phone_links = mail_links = 0
    for a in ctx.dom.find_all("a", href=True):
        href = str(a["href"]).strip().lower()
        if href.startswith("tel:"):
            phone_links += 1
            continue
        if href.startswith("mailto:"):
            mail_links += 1
            continue
        link = normalize_link(a["href"], ctx.final_url)
        if not link or link in seen:
            continue
        seen.add(link)
        entry: dict[str, Any] = {"text": _text(a, 80), "href": redact_text(link)}
        status, error = ctx.link_results.get(link, (None, None))
        if status is not None or error:
            entry["status"] = status if status is not None else error
        (internal if same_site(link, ctx.final_url) else external).append(entry)
    return {
        "internal": internal[:MAX_LINKS],
        "external": external[:MAX_LINKS],
        "internal_count": len(internal),
        "external_count": len(external),
        "phone_links": phone_links,
        "email_links": mail_links,
    }


def _images(ctx: ScanContext) -> list[dict[str, Any]]:
    sizes: dict[str, int] = dict(ctx.image_bytes)
    for request in ctx.all_requests():
        if request.get("type") == "image" and request.get("bytes"):
            sizes[request["url"]] = max(sizes.get(request["url"], 0), int(request["bytes"]))
    out = []
    for img in ctx.dom.find_all("img")[:MAX_IMAGES]:
        src = _attr(img, "src") or _attr(img, "data-src") or ""
        absolute = urljoin(ctx.final_url, src) if src and not src.startswith("data:") else (src[:40] + "…" if src else "")
        alt = img.get("alt")
        out.append(
            {
                "src": absolute,
                "alt": redact_text(str(alt)) if alt is not None else None,
                "width": _attr(img, "width"),
                "height": _attr(img, "height"),
                "loading": _attr(img, "loading"),
                "bytes": sizes.get(absolute),
                "selector": css_path(img),
            }
        )
    return out


def _forms(dom: BeautifulSoup, base: str) -> list[dict[str, Any]]:
    out = []
    for form in dom.find_all("form")[:10]:
        fields = []
        for field in form.find_all(["input", "select", "textarea"]):
            kind = (_attr(field, "type") or field.name).lower()
            if kind in FIELD_TYPES_SKIPPED:
                continue
            fields.append({"type": kind, "name": _attr(field, "name"), "selector": css_path(field)})
        action = _attr(form, "action")
        out.append(
            {
                "selector": css_path(form),
                "action": redact_text(urljoin(base, action)) if action else None,  # old forms post to mailto:
                "method": (_attr(form, "method") or "get").lower(),
                "fields": fields[:30],
            }
        )
    return out


def _assets(ctx: ScanContext) -> dict[str, Any]:
    dom, base = ctx.dom, ctx.final_url
    scripts = [urljoin(base, s) for s in (_attr(t, "src") for t in dom.find_all("script")) if s]
    inline = sum(1 for t in dom.find_all("script") if not t.get("src") and (t.string or "").strip())
    styles = [urljoin(base, h) for h in (_attr(t, "href") for t in dom.find_all("link", rel=lambda r: r and "stylesheet" in r)) if h]
    iframes = [urljoin(base, s) for s in (_attr(t, "src") for t in dom.find_all("iframe")) if s]
    families = ((ctx.desktop.metrics.get("fonts") or {}).get("families") or {}) if ctx.browser_ok else {}
    requests = ctx.desktop.requests if ctx.browser_ok else []
    by_type: dict[str, dict[str, int]] = {}
    for request in requests:
        bucket = by_type.setdefault(request.get("type") or "other", {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += int(request.get("bytes") or 0)
    third_party = sorted({urlsplit(r["url"]).hostname or "" for r in requests if not same_site(r["url"], base)} - {""})
    return {
        "scripts": scripts[:MAX_ASSETS],
        "inline_scripts": inline,
        "stylesheets": styles[:MAX_ASSETS],
        "iframes": iframes[:20],
        "fonts": sorted(families, key=lambda f: -families[f])[:12],
        "requests_by_type": by_type,
        "third_party_hosts": third_party[:40],
    }


def build(ctx: ScanContext) -> dict[str, Any]:
    blocks = _content_blocks(ctx.dom)
    inventory: dict[str, Any] = {
        "source": "rendered" if ctx.browser_ok else "static",
        "meta": _meta(ctx.dom, ctx.static_dom),
        "headings": [{"level": int(h.name[1]), "text": _text(h, 200)} for h in ctx.dom.find_all(HEADINGS) if h.get_text(strip=True)][:80],
        "navigation": _navigation(ctx.dom, ctx.final_url),
        "content": blocks,
        "links": _links(ctx),
        "images": _images(ctx),
        "forms": _forms(ctx.dom, ctx.final_url),
        "structured_data": sorted(set(json_ld_types(ctx.static_dom) + json_ld_types(ctx.dom))),
        "assets": _assets(ctx),
        "contact_page": ctx.contact_url,
        "cookie_banner": dict(ctx.desktop.cookie) if ctx.browser_ok else None,
    }
    # Page builders often keep text in plain <div>s; fall back to the visible text then.
    block_chars = sum(len(b["text"]) for b in blocks)
    text = redact_text(visible_text(ctx.dom.find("body") or ctx.dom))
    if block_chars < len(text) / 2:
        inventory["text"] = text[:MAX_TEXT_CHARS]
    return inventory
