"""Automatic signs of an outdated design. The AI review (stage 4) adds a judgement on top."""

from __future__ import annotations

from ..context import ScanContext
from ..models import Area, Status
from . import check, grade, na, plural, result

A = Area.DESIGN
LAYOUT_TABLE_ATTRS = ("bgcolor", "background", "cellpadding", "cellspacing")
NO_BROWSER = "Needs the browser (Playwright) to measure"


@check("design.fixed_width", A)
def fixed_width(ctx: ScanContext):
    if not ctx.browser_ok:
        return na("design.fixed_width", A, NO_BROWSER)
    narrow = ctx.desktop.metrics.get("narrow") or {}
    width, scroll = narrow.get("viewport_width"), narrow.get("scroll_width")
    if not width or not scroll:
        return na("design.fixed_width", A, "Layout could not be measured at a narrow width")
    overflow = scroll - width
    value = {"viewport_width": width, "scroll_width": scroll}
    if overflow > ctx.t("fixed_width_tolerance_px"):
        return result(
            "design.fixed_width", A, Status.FAIL, f"Layout keeps a fixed width of about {scroll}px and does not adapt", value=value
        )
    return result("design.fixed_width", A, Status.PASS, "Layout adapts to the window width", value=value)


@check("design.table_layout", A)
def table_layout(ctx: ScanContext):
    tables = ctx.dom.find_all("table")
    if not tables:
        return result("design.table_layout", A, Status.PASS, "No tables used for layout", value=0)
    layout = 0
    for table in tables:
        if table.get("role") in ("presentation", "none"):
            layout += 1
            continue
        if table.find("th") or table.find("caption"):
            continue  # data table
        nested = table.find("table") is not None
        legacy_attrs = any(table.get(attr) is not None for attr in LAYOUT_TABLE_ATTRS)
        blocks = len(table.find_all(["img", "ul", "form", "iframe", "nav", "h1", "h2"]))
        if nested or (legacy_attrs and blocks) or blocks >= 4:
            layout += 1
    if layout:
        return result("design.table_layout", A, Status.FAIL, f"{plural(layout, 'table')} used to lay out the page", value=layout)
    return result("design.table_layout", A, Status.PASS, "No tables used for layout", value=0)


@check("design.small_text", A)
def small_text(ctx: ScanContext):
    if not ctx.browser_ok:
        return na("design.small_text", A, NO_BROWSER)
    fonts = ctx.desktop.metrics.get("fonts") or {}
    total = fonts.get("total_chars") or 0
    if total < 50:
        return na("design.small_text", A, "Too little text to judge")
    ratio = fonts.get("chars_below_small", 0) / total
    status = grade(ratio, warn_at=ctx.t("desktop_small_text_ratio_warn"), fail_at=ctx.t("desktop_small_text_ratio_fail"))
    return result(
        "design.small_text",
        A,
        status,
        f"{ratio:.0%} of text is smaller than {ctx.t('desktop_small_font_px')}px on desktop",
        value={"small_ratio": round(ratio, 3), "body_px": fonts.get("body_px")},
    )


@check("design.font_count", A)
def font_count(ctx: ScanContext):
    if not ctx.browser_ok:
        return na("design.font_count", A, NO_BROWSER)
    families: dict[str, int] = (ctx.desktop.metrics.get("fonts") or {}).get("families") or {}
    icon_markers = ctx.signatures["icon_fonts"]
    total = sum(families.values()) or 1
    # Ignore icon fonts and families used for a negligible share of text.
    used = sorted(
        (f for f, chars in families.items() if not any(m in f for m in icon_markers) and chars / total >= 0.01),
        key=lambda f: -families[f],
    )
    count = len(used)
    status = Status.PASS
    if count >= ctx.t("font_families_fail"):
        status = Status.FAIL
    elif count >= ctx.t("font_families_warn"):
        status = Status.WARN
    return result("design.font_count", A, status, f"{plural(count, 'font family', 'font families')} in use", value=count, evidence=used)


@check("design.legacy_markup", A)
def legacy_markup(ctx: ScanContext):
    found: dict[str, int] = {}
    for tag in ctx.signatures["legacy_tags"]:
        count = len(ctx.static_dom.find_all(tag))
        if count:
            found[f"<{tag}>"] = count
    flash = [
        t
        for t in ctx.static_dom.find_all(["embed", "object"])
        if ".swf" in str(t.get("src") or t.get("data") or "").lower() or "flash" in str(t.get("type") or "").lower()
    ]
    if flash:
        found["Flash"] = len(flash)
    body = ctx.static_dom.find("body")
    if body is not None and any(body.get(a) for a in ("bgcolor", "background", "text", "link")):
        found["<body bgcolor>"] = 1
    if found:
        evidence = [f"{k} ×{v}" for k, v in found.items()]
        return result(
            "design.legacy_markup",
            A,
            Status.FAIL,
            "Outdated HTML from the early 2000s: " + ", ".join(found),
            value=found,
            evidence=evidence,
        )
    return result("design.legacy_markup", A, Status.PASS, "No outdated HTML elements", value={})
