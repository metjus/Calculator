from __future__ import annotations

import re

from ..context import ScanContext
from ..dom import json_ld_types, meta_content, normalize_link, visible_text
from ..models import Area, Status
from ..redact import redact_text
from . import check, na, result

A = Area.SEO


def _is_canonical(rel) -> bool:
    return bool(rel) and "canonical" in rel


@check("seo.title", A)
def title(ctx: ScanContext):
    tag = ctx.dom.find("title") or ctx.static_dom.find("title")
    text = " ".join(tag.get_text().split()) if tag else ""
    if not text:
        return result("seo.title", A, Status.FAIL, "Page has no title", value=None)
    length = len(text)
    value = {"length": length, "text": redact_text(text[:120])}
    if text.lower() in ctx.t("generic_titles"):
        return result("seo.title", A, Status.WARN, f"Generic title “{value['text']}”", value=value)
    if length < ctx.t("title_min_chars") or length > ctx.t("title_max_chars"):
        return result(
            "seo.title",
            A,
            Status.WARN,
            f"Title has {length} characters (aim for {ctx.t('title_min_chars')}–{ctx.t('title_max_chars')})",
            value=value,
        )
    return result("seo.title", A, Status.PASS, f"Title has {length} characters", value=value)


@check("seo.canonical", A)
def canonical(ctx: ScanContext):
    """Where the homepage tells Google its real address is.

    A homepage that points the canonical somewhere else asks Google to index that page
    instead - usually a copy-paste mistake from a template, and it costs the site its own
    listing. No canonical at all is only a warning: Google guesses, and usually guesses right.
    """
    tag = ctx.dom.find("link", rel=_is_canonical) or ctx.static_dom.find("link", rel=_is_canonical)
    href = (tag.get("href") or "").strip() if tag else ""
    if not href:
        return result("seo.canonical", A, Status.WARN, "Homepage has no canonical link", value=None)
    target = normalize_link(href, ctx.final_url)
    if not target:
        return result("seo.canonical", A, Status.WARN, f"Canonical link cannot be read: {redact_text(href[:120])}", value=href[:120])
    here = normalize_link(ctx.final_url, ctx.final_url)
    value = {"canonical": redact_text(target), "page": redact_text(here or ctx.final_url)}
    if target != here:
        return result(
            "seo.canonical",
            A,
            Status.FAIL,
            f"Homepage points search engines to another address ({redact_text(target)})",
            value=value,
            evidence=[target],
        )
    return result("seo.canonical", A, Status.PASS, "Homepage points to itself", value=value)


@check("seo.thin_content", A)
def thin_content(ctx: ScanContext):
    """How much the homepage actually says.

    Counted on the rendered page when a browser ran, so text a script writes in still counts.
    A page of pictures and three words gives Google nothing to match a search against, and
    tells a visitor just as little.
    """
    body = ctx.dom.find("body") or ctx.dom
    words = len(visible_text(body).split())
    warn, fail = ctx.t("homepage_words_warn"), ctx.t("homepage_words_fail")
    value = {"words": words}
    if words < fail:
        return result("seo.thin_content", A, Status.FAIL, f"Homepage has about {words} words of text", value=value)
    if words < warn:
        return result("seo.thin_content", A, Status.WARN, f"Homepage has about {words} words of text", value=value)
    return result("seo.thin_content", A, Status.PASS, f"Homepage has about {words} words of text", value=value)


@check("seo.meta_description", A)
def meta_description(ctx: ScanContext):
    text = meta_content(ctx.dom, name="description") or meta_content(ctx.static_dom, name="description")
    if not text:
        return result("seo.meta_description", A, Status.FAIL, "No meta description", value=None)
    length = len(text)
    if length < ctx.t("meta_description_min_chars") or length > ctx.t("meta_description_max_chars"):
        return result("seo.meta_description", A, Status.WARN, f"Meta description has {length} characters", value=length)
    return result("seo.meta_description", A, Status.PASS, f"Meta description has {length} characters", value=length)


@check("seo.h1", A)
def h1(ctx: ScanContext):
    headings = [h for h in ctx.dom.find_all("h1") if h.get_text(strip=True)]
    count = len(headings)
    if count == 0:
        return result("seo.h1", A, Status.FAIL, "No main heading (H1)", value=0)
    if count > 1:
        return result("seo.h1", A, Status.WARN, f"{count} H1 headings; one is recommended", value=count)
    return result("seo.h1", A, Status.PASS, "One H1 heading", value=1)


@check("seo.indexable", A)
def indexable(ctx: ScanContext):
    robots_meta = " ".join(
        (tag.get("content") or "").lower()
        for tag in ctx.static_dom.find_all("meta", attrs={"name": re.compile("^(robots|googlebot)$", re.I)})
    )
    header = ctx.home.headers.get("x-robots-tag", "").lower()
    if "noindex" in robots_meta or "noindex" in header or "none" in robots_meta.split(","):
        return result("seo.indexable", A, Status.FAIL, "Homepage tells search engines not to index it (noindex)", value=False)
    if not ctx.robots.can_fetch("Googlebot", "/"):
        return result("seo.indexable", A, Status.FAIL, "robots.txt blocks Google from the homepage", value=False)
    return result("seo.indexable", A, Status.PASS, "Homepage can be indexed", value=True)


@check("seo.sitemap", A)
def sitemap(ctx: ScanContext):
    if ctx.sitemap_found is None:
        return na("seo.sitemap", A, "Sitemap not checked")
    if ctx.sitemap_found:
        return result("seo.sitemap", A, Status.PASS, "XML sitemap found", value=True)
    return result("seo.sitemap", A, Status.FAIL, "No XML sitemap found", value=False)


@check("seo.open_graph", A)
def open_graph(ctx: ScanContext):
    present = {key: bool(meta_content(ctx.dom, prop=f"og:{key}")) for key in ("title", "description", "image")}
    if present["title"] and present["image"]:
        return result("seo.open_graph", A, Status.PASS, "Share preview (Open Graph) is set", value=present)
    if any(present.values()):
        missing = ", ".join(k for k, v in present.items() if not v)
        return result("seo.open_graph", A, Status.WARN, f"Share preview incomplete, missing og:{missing}", value=present)
    return result("seo.open_graph", A, Status.FAIL, "No share preview (Open Graph) tags", value=present)


@check("seo.favicon", A)
def favicon(ctx: ScanContext):
    if ctx.favicon_found is None:
        return na("seo.favicon", A, "Favicon not checked")
    if ctx.favicon_found:
        return result("seo.favicon", A, Status.PASS, "Favicon present", value=True)
    return result("seo.favicon", A, Status.FAIL, "No favicon", value=False)


@check("seo.structured_data", A)
def structured_data(ctx: ScanContext):
    types = json_ld_types(ctx.dom) or json_ld_types(ctx.static_dom)
    local = set(ctx.signatures["local_business_types"])
    matches = sorted({t for t in types if t in local})
    if matches:
        return result("seo.structured_data", A, Status.PASS, f"Business details marked up ({', '.join(matches)})", value=matches)
    if types:
        return result(
            "seo.structured_data",
            A,
            Status.WARN,
            f"Structured data present but no LocalBusiness ({', '.join(sorted(set(types))[:5])})",
            value=sorted(set(types)),
        )
    return result("seo.structured_data", A, Status.FAIL, "No structured data (LocalBusiness) for search engines", value=[])
