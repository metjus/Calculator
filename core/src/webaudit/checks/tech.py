from __future__ import annotations

from ..context import ScanContext
from ..models import Area, Status
from ..redact import redact_text
from ..techdetect import detect_cms, detect_libraries, rate_version
from . import check, na, plural, result

A = Area.TECH


@check("tech.cms_version", A)
def cms_version(ctx: ScanContext):
    cms, version, rule = detect_cms(ctx)
    if cms is None:
        return na("tech.cms_version", A, "No known CMS detected")
    if not version:
        return na("tech.cms_version", A, f"{cms} detected, version hidden")
    status = rate_version(version, rule or {})
    if status is Status.NA:
        return na("tech.cms_version", A, f"{cms} {version} (no version policy configured)")
    label = {Status.PASS: "is current", Status.WARN: "is getting old", Status.FAIL: "is outdated"}[status]
    return result("tech.cms_version", A, status, f"{cms} {version} {label}", value={"cms": cms, "version": version})


@check("tech.outdated_libraries", A)
def outdated_libraries(ctx: ScanContext):
    libs = detect_libraries(ctx)
    bad = [lib for lib in libs if lib.status in (Status.FAIL, Status.WARN)]
    evidence = [f"{lib.name} {lib.version or ''}".strip() for lib in bad]
    value = [lib.model_dump() for lib in libs]
    if any(lib.status is Status.FAIL for lib in libs):
        return result(
            "tech.outdated_libraries", A, Status.FAIL, f"Outdated libraries: {', '.join(evidence)}", value=value, evidence=evidence
        )
    if bad:
        return result("tech.outdated_libraries", A, Status.WARN, f"Ageing libraries: {', '.join(evidence)}", value=value, evidence=evidence)
    return result("tech.outdated_libraries", A, Status.PASS, "No outdated libraries detected", value=value)


@check("tech.console_errors", A)
def console_errors(ctx: ScanContext):
    if not ctx.browser_ok:
        return na("tech.console_errors", A, "Needs the browser (Playwright) to measure")
    errors = []
    for render in (ctx.desktop, ctx.mobile):
        if render and render.ok:
            errors.extend(e for e in render.console_errors if e not in errors)
    count = len(errors)
    status = Status.PASS
    if count >= ctx.t("console_errors_fail"):
        status = Status.FAIL
    elif count >= ctx.t("console_errors_warn"):
        status = Status.WARN
    return result(
        "tech.console_errors",
        A,
        status,
        f"{plural(count, 'JavaScript error')} while loading",
        value=count,
        evidence=[redact_text(e[:160]) for e in errors],  # messages can quote page text
    )


ACTIVE_TAGS = {"script": "src", "iframe": "src", "object": "data", "embed": "src"}
PASSIVE_TAGS = {"img": "src", "audio": "src", "video": "src", "source": "src"}


@check("tech.mixed_content", A)
def mixed_content(ctx: ScanContext):
    if not ctx.is_https:
        return na("tech.mixed_content", A, "Site is not on HTTPS")
    active: list[str] = []
    passive: list[str] = []
    for dom in (ctx.static_dom, ctx.dom):
        for tag, attr in ACTIVE_TAGS.items():
            active += [str(t.get(attr)) for t in dom.find_all(tag) if str(t.get(attr) or "").startswith("http://")]
        active += [
            str(t.get("href"))
            for t in dom.find_all("link", rel=lambda r: r and "stylesheet" in r)
            if str(t.get("href") or "").startswith("http://")
        ]
        for tag, attr in PASSIVE_TAGS.items():
            passive += [str(t.get(attr)) for t in dom.find_all(tag) if str(t.get(attr) or "").startswith("http://")]
    for render in (ctx.desktop, ctx.mobile):
        if render and render.ok:
            active += [e for e in render.console_errors if "mixed content" in e.lower()]
    active, passive = sorted(set(active)), sorted(set(passive) - set(active))
    if active:
        return result(
            "tech.mixed_content",
            A,
            Status.FAIL,
            f"{plural(len(active), 'insecure script, style or frame', 'insecure scripts, styles or frames')} on an HTTPS page",
            value={"active": len(active), "passive": len(passive)},
            evidence=active,
        )
    if passive:
        return result(
            "tech.mixed_content",
            A,
            Status.WARN,
            f"{plural(len(passive), 'insecure image or media file', 'insecure images or media files')} on an HTTPS page",
            value={"active": 0, "passive": len(passive)},
            evidence=passive,
        )
    return result("tech.mixed_content", A, Status.PASS, "No insecure (http://) content", value={"active": 0, "passive": 0})
