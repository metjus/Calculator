from __future__ import annotations

import re

from ..context import ScanContext
from ..models import Area, Status
from . import check, grade, na, plural, result

A = Area.MOBILE
NO_BROWSER = "Needs the browser (Playwright) to measure"


def _viewport_content(ctx: ScanContext) -> str | None:
    for dom in (ctx.static_dom, ctx.dom):
        tag = dom.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
        if tag is not None:
            return (tag.get("content") or "").lower().replace(" ", "")
    return None


def has_mobile_viewport(ctx: ScanContext) -> bool:
    return "width=device-width" in (_viewport_content(ctx) or "")


@check("mobile.viewport", A)
def viewport(ctx: ScanContext):
    content = _viewport_content(ctx)
    if content is None:
        return result("mobile.viewport", A, Status.FAIL, "No viewport meta tag; phones show a zoomed-out desktop page", value=None)
    if "width=device-width" not in content:
        return result("mobile.viewport", A, Status.FAIL, f"Viewport is not set to device width ({content or 'empty'})", value=content)
    if "user-scalable=no" in content or "user-scalable=0" in content or re.search(r"maximum-scale=(1(\.0)?|0\.\d+)(,|$)", content):
        return result("mobile.viewport", A, Status.WARN, "Viewport blocks zooming (user-scalable=no / maximum-scale=1)", value=content)
    return result("mobile.viewport", A, Status.PASS, "Responsive viewport is set", value=content)


@check("mobile.font_size", A)
def font_size(ctx: ScanContext):
    if not ctx.mobile_ok:
        return na("mobile.font_size", A, NO_BROWSER)
    fonts = ctx.mobile.metrics.get("fonts") or {}
    total = fonts.get("total_chars") or 0
    if total < 50:
        return na("mobile.font_size", A, "Too little text to judge")
    ratio = 1 - (fonts.get("chars_below_min", 0) / total)
    value = {"legible_ratio": round(ratio, 3), "scale": fonts.get("scale")}
    if not has_mobile_viewport(ctx):
        # Like Lighthouse: without a mobile viewport the whole page is shown shrunk;
        # Chrome's text autosizing only partly hides that, so don't trust the ratio.
        return result("mobile.font_size", A, Status.FAIL, "No mobile viewport, so text is shown shrunk on phones", value=value)
    pct = f"{ratio:.0%} of text is at least {ctx.t('mobile_min_font_px')}px on a phone"
    if ratio < ctx.t("mobile_legible_ratio_fail"):
        return result("mobile.font_size", A, Status.FAIL, pct, value=value)
    if ratio < ctx.t("mobile_legible_ratio_pass"):
        return result("mobile.font_size", A, Status.WARN, pct, value=value)
    return result("mobile.font_size", A, Status.PASS, pct, value=value)


@check("mobile.tap_targets", A)
def tap_targets(ctx: ScanContext):
    if not ctx.mobile_ok:
        return na("mobile.tap_targets", A, NO_BROWSER)
    data = ctx.mobile.metrics.get("tap_targets") or {}
    total = data.get("total") or 0
    if total < 3:
        return na("mobile.tap_targets", A, "Too few links or buttons to judge")
    failing = data.get("failing", 0)
    ratio = failing / total
    status = grade(ratio, warn_at=ctx.t("tap_target_fail_ratio_warn"), fail_at=ctx.t("tap_target_fail_ratio_fail"))
    return result(
        "mobile.tap_targets",
        A,
        status,
        f"{failing} of {plural(total, 'link or button', 'links and buttons')} too small or too close together",
        value={"failing": failing, "total": total},
        evidence=data.get("samples", []),
    )


@check("mobile.horizontal_scroll", A)
def horizontal_scroll(ctx: ScanContext):
    if not ctx.mobile_ok:
        return na("mobile.horizontal_scroll", A, NO_BROWSER)
    layout = ctx.mobile.metrics.get("layout") or {}
    scroll_width, client_width = layout.get("scroll_width"), layout.get("client_width")
    if not scroll_width or not client_width:
        return na("mobile.horizontal_scroll", A, "Layout could not be measured")
    overflow = scroll_width - client_width
    value = {"scroll_width": scroll_width, "client_width": client_width}
    if overflow > ctx.t("horizontal_scroll_tolerance_px"):
        return result(
            "mobile.horizontal_scroll",
            A,
            Status.FAIL,
            f"Page is {overflow}px wider than the phone screen",
            value=value,
            evidence=layout.get("wide_elements", []),
        )
    return result("mobile.horizontal_scroll", A, Status.PASS, "No sideways scrolling on a phone", value=value)
