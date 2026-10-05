from __future__ import annotations

from urllib.parse import urlsplit

from ..context import ScanContext
from ..models import Area, Status
from . import check, grade, na, plural, result

A = Area.SPEED


def _psi_score(ctx: ScanContext, strategy: str) -> int | None:
    data = ctx.pagespeed.get(strategy)
    if not data:
        return None
    score = (((data.get("lighthouseResult") or {}).get("categories") or {}).get("performance") or {}).get("score")
    return None if score is None else round(score * 100)


def _psi_check(ctx: ScanContext, strategy: str):
    check_id = f"speed.pagespeed_{strategy}"
    score = _psi_score(ctx, strategy)
    if score is None:
        return na(check_id, A, ctx.pagespeed_note or "PageSpeed result unavailable")
    if score >= ctx.t("pagespeed_pass"):
        status = Status.PASS
    elif score < ctx.t("pagespeed_fail_below"):
        status = Status.FAIL
    else:
        status = Status.WARN
    return result(check_id, A, status, f"PageSpeed {strategy} score {score}/100", value=score)


@check("speed.pagespeed_mobile", A)
def pagespeed_mobile(ctx: ScanContext):
    return _psi_check(ctx, "mobile")


@check("speed.pagespeed_desktop", A)
def pagespeed_desktop(ctx: ScanContext):
    return _psi_check(ctx, "desktop")


def _rate(value: float | None, good: float, poor: float) -> Status | None:
    if value is None:
        return None
    if value <= good:
        return Status.PASS
    if value <= poor:
        return Status.WARN
    return Status.FAIL


def _worst(statuses: list[Status]) -> Status:
    order = [Status.FAIL, Status.WARN, Status.PASS]
    return next(s for s in order if s in statuses)


@check("speed.core_web_vitals", A)
def core_web_vitals(ctx: ScanContext):
    data = ctx.pagespeed.get("mobile")
    if not data:
        return na("speed.core_web_vitals", A, ctx.pagespeed_note or "PageSpeed result unavailable")
    cwv = ctx.t("cwv")
    field = ((data.get("loadingExperience") or {}).get("metrics")) or {}
    if field.get("LARGEST_CONTENTFUL_PAINT_MS"):
        lcp = field.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("percentile")
        inp = (field.get("INTERACTION_TO_NEXT_PAINT") or {}).get("percentile")
        cls_raw = (field.get("CUMULATIVE_LAYOUT_SHIFT_SCORE") or {}).get("percentile")
        cls = None if cls_raw is None else cls_raw / 100
        values = {"source": "field", "lcp_ms": lcp, "inp_ms": inp, "cls": cls}
        rated = [
            _rate(lcp, cwv["lcp_good_ms"], cwv["lcp_poor_ms"]),
            _rate(inp, cwv["inp_good_ms"], cwv["inp_poor_ms"]),
            _rate(cls, cwv["cls_good"], cwv["cls_poor"]),
        ]
    else:
        audits = (data.get("lighthouseResult") or {}).get("audits") or {}

        def numeric(name: str) -> float | None:
            return (audits.get(name) or {}).get("numericValue")

        lcp, cls, tbt = numeric("largest-contentful-paint"), numeric("cumulative-layout-shift"), numeric("total-blocking-time")
        values = {"source": "lab", "lcp_ms": lcp, "cls": cls, "tbt_ms": tbt}
        rated = [
            _rate(lcp, cwv["lcp_good_ms"], cwv["lcp_poor_ms"]),
            _rate(cls, cwv["cls_good"], cwv["cls_poor"]),
            _rate(tbt, cwv["tbt_good_ms"], cwv["tbt_poor_ms"]),
        ]
    rated = [r for r in rated if r is not None]
    if not rated:
        return na("speed.core_web_vitals", A, "No Core Web Vitals in the PageSpeed response")
    status = _worst(rated)
    parts = []
    if values.get("lcp_ms") is not None:
        parts.append(f"LCP {values['lcp_ms'] / 1000:.1f}s")
    if values.get("inp_ms") is not None:
        parts.append(f"INP {values['inp_ms']:.0f}ms")
    if values.get("tbt_ms") is not None:
        parts.append(f"TBT {values['tbt_ms']:.0f}ms")
    if values.get("cls") is not None:
        parts.append(f"CLS {values['cls']:.2f}")
    return result("speed.core_web_vitals", A, status, f"{values['source']} data: " + ", ".join(parts), value=values)


@check("speed.large_images", A)
def large_images(ctx: ScanContext):
    large_at, huge_at = ctx.t("large_image_bytes"), ctx.t("huge_image_bytes")
    sizes: dict[str, int] = {}
    if ctx.browser_ok:
        for req in ctx.all_requests():
            if req.get("type") == "image" and req.get("bytes"):
                sizes[req["url"]] = max(sizes.get(req["url"], 0), int(req["bytes"]))
        oversized = (ctx.desktop.metrics.get("images") or {}).get("oversized", [])
    else:
        sizes = dict(ctx.image_bytes)
        oversized = []
    if not sizes and not oversized:
        return na("speed.large_images", A, "No images measured")
    heavy = sorted(((u, b) for u, b in sizes.items() if b >= large_at), key=lambda x: -x[1])
    huge = [u for u, b in heavy if b >= huge_at]
    evidence = [f"{urlsplit(u).path or u} ({b // 1024} KB)" for u, b in heavy] + [f"{o} (scaled down in the browser)" for o in oversized]
    value = {"heavy": len(heavy), "huge": len(huge), "oversized": len(oversized)}
    problems = len(heavy) + len(oversized)
    if huge or problems >= 3:
        status = Status.FAIL
    elif problems:
        status = Status.WARN
    else:
        status = Status.PASS
    return result(
        "speed.large_images",
        A,
        status,
        f"{plural(len(heavy), 'heavy image')}, {len(oversized)} far larger than displayed",
        value=value,
        evidence=evidence,
    )


@check("speed.page_weight", A)
def page_weight(ctx: ScanContext):
    if not ctx.browser_ok:
        return na("speed.page_weight", A, "Needs the browser (Playwright) to measure")
    total = sum(int(r.get("bytes") or 0) for r in ctx.desktop.requests)
    if not total:
        return na("speed.page_weight", A, "Transfer sizes unavailable")
    status = grade(total, warn_at=ctx.t("page_weight_warn_bytes"), fail_at=ctx.t("page_weight_fail_bytes"))
    return result("speed.page_weight", A, status, f"Homepage downloads {total / 1_000_000:.1f} MB", value=total)


@check("speed.server_response", A)
def server_response(ctx: ScanContext):
    elapsed = ctx.home.elapsed_s
    if elapsed is None:
        return na("speed.server_response", A, "Response time unknown")
    status = grade(elapsed, warn_at=ctx.t("server_response_warn_s"), fail_at=ctx.t("server_response_fail_s"))
    return result("speed.server_response", A, status, f"Server answered in {elapsed:.2f}s", value=round(elapsed, 3))
