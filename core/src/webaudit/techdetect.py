"""CMS and JavaScript library detection."""

from __future__ import annotations

import re

from .context import ScanContext
from .models import LibraryInfo, Status, TechInfo


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:4])


def version_below(version: str, limit: str) -> bool:
    a, b = version_tuple(version), version_tuple(limit)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) < b + (0,) * (width - len(b))


def rate_version(version: str | None, rule: dict) -> Status:
    if not version:
        return Status.NA
    if rule.get("fail_below") and version_below(version, rule["fail_below"]):
        return Status.FAIL
    if rule.get("warn_below") and version_below(version, rule["warn_below"]):
        return Status.WARN
    return Status.PASS


def _generator(ctx: ScanContext) -> str:
    values = [
        (tag.get("content") or "")
        for dom in (ctx.static_dom, ctx.dom)
        for tag in dom.find_all("meta", attrs={"name": re.compile("^generator$", re.I)})
    ]
    return " | ".join(values)


def detect_cms(ctx: ScanContext) -> tuple[str | None, str | None, dict | None]:
    if "cms" not in ctx.memo:
        ctx.memo["cms"] = _detect_cms(ctx)
    return ctx.memo["cms"]


def _detect_cms(ctx: ScanContext) -> tuple[str | None, str | None, dict | None]:
    html = ctx.home.text[:600_000]
    rendered = ctx.desktop.html[:600_000] if ctx.desktop and ctx.desktop.ok else ""
    generator = _generator(ctx)
    gen_lower = generator.lower()
    headers = ctx.home.headers
    for rule in ctx.signatures["cms"]:
        hit = False
        if rule.get("generator") and rule["generator"] in gen_lower:
            hit = True
        if not hit:
            lowered = (html + rendered).lower()
            hit = any(marker.lower() in lowered for marker in rule.get("html", []))
        if not hit:
            for name, needle in (rule.get("headers") or {}).items():
                if name in headers and needle.lower() in headers[name].lower():
                    hit = True
        if not hit:
            continue
        version = None
        for pattern in rule.get("version_regex", []):
            match = re.search(pattern, generator, re.I) or re.search(pattern, html, re.I)
            if match:
                version = match.group(1)
                break
        return rule["name"], version, rule
    return None, None, None


def detect_libraries(ctx: ScanContext) -> list[LibraryInfo]:
    if "libraries" not in ctx.memo:
        ctx.memo["libraries"] = _detect_libraries(ctx)
    return ctx.memo["libraries"]


def _detect_libraries(ctx: ScanContext) -> list[LibraryInfo]:
    urls = [str(s.get("src") or "") for s in ctx.static_dom.find_all("script")]
    urls += [str(link.get("href") or "") for link in ctx.static_dom.find_all("link")]
    urls += [r.get("url", "") for r in ctx.all_requests() if r.get("type") in ("script", "stylesheet")]
    runtime: dict[str, str] = {}
    if ctx.browser_ok:
        runtime = {k: v for k, v in (ctx.desktop.metrics.get("libraries") or {}).items() if v}
    found: list[LibraryInfo] = []
    for rule in ctx.signatures["libraries"]:
        version = runtime.get(rule.get("runtime", ""))
        present = bool(version)
        if not version:
            for url in urls:
                for pattern in rule["url_regex"]:
                    match = re.search(pattern, url, re.I)
                    if match:
                        present = True
                        if match.groups():
                            version = match.group(1)
                        break
                if version:
                    break
        if not present:
            continue
        if version and version.lower() in ("true", "present"):
            version = None
        status = rate_version(version, rule)
        if version is None and rule.get("fail_below") == "99.0.0":
            status = Status.FAIL  # obsolete regardless of version (Flash, MooTools...)
        found.append(LibraryInfo(name=rule["name"], version=version, status=status))
    return found


def detect(ctx: ScanContext) -> TechInfo:
    cms, version, _rule = detect_cms(ctx)
    return TechInfo(cms=cms, cms_version=version, libraries=detect_libraries(ctx))
