from __future__ import annotations

from bs4 import Tag

from ..context import ScanContext
from ..dom import css_path
from ..models import Area, Status
from ..redact import redact_text
from . import check, grade, na, plural, result

A = Area.ACCESSIBILITY

UNLABELLED_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}


@check("a11y.contrast", A)
def contrast(ctx: ScanContext):
    if not ctx.browser_ok:
        return na("a11y.contrast", A, "Needs the browser (Playwright) to measure")
    data = ctx.desktop.metrics.get("contrast") or {}
    checked = data.get("checked", 0)
    if checked < ctx.t("contrast_min_checked"):
        return na("a11y.contrast", A, "Too little measurable text")
    failing = data.get("failing", 0)
    status = grade(failing / checked, warn_at=ctx.t("contrast_fail_ratio_warn"), fail_at=ctx.t("contrast_fail_ratio_fail"))
    return result(
        "a11y.contrast",
        A,
        status,
        f"{failing} of {checked} text blocks have low contrast",
        value={"failing": failing, "checked": checked},
        evidence=data.get("samples", []),
    )


def _is_decorative(img: Tag) -> bool:
    if img.get("aria-hidden") == "true" or (img.get("role") or "") in ("presentation", "none"):
        return True
    width, height = str(img.get("width") or ""), str(img.get("height") or "")
    return width in ("0", "1") or height in ("0", "1")


@check("a11y.img_alt", A)
def img_alt(ctx: ScanContext):
    images = [img for img in ctx.dom.find_all("img") if not _is_decorative(img)]
    if not images:
        return na("a11y.img_alt", A, "No images")
    missing = [img for img in images if img.get("alt") is None]
    ratio = len(missing) / len(images)
    evidence = [f"{css_path(img)}: {str(img.get('src') or img.get('data-src') or '')[-100:]}" for img in missing]
    summary = f"{len(missing)} of {plural(len(images), 'image')} without a text description (alt)"
    value = {"missing": len(missing), "total": len(images)}
    if ratio > ctx.t("img_alt_missing_ratio_fail"):
        return result("a11y.img_alt", A, Status.FAIL, summary, value=value, evidence=evidence)
    if missing:
        return result("a11y.img_alt", A, Status.WARN, summary, value=value, evidence=evidence)
    return result("a11y.img_alt", A, Status.PASS, summary, value=value)


def _has_label(field: Tag) -> str:
    """Return 'label', 'placeholder' or '' for a form field."""
    if field.get("aria-label", "").strip() or field.get("aria-labelledby") or field.get("title", "").strip():
        return "label"
    field_id = field.get("id")
    root = field
    while root.parent is not None:
        root = root.parent
    if field_id and root.find("label", attrs={"for": field_id}):
        return "label"
    if field.find_parent("label") is not None:
        return "label"
    if field.get("placeholder", "").strip():
        return "placeholder"
    return ""


@check("a11y.form_labels", A)
def form_labels(ctx: ScanContext):
    fields = [
        f
        for f in ctx.dom.find_all(["input", "select", "textarea"])
        if (f.get("type") or "text").lower() not in UNLABELLED_INPUT_TYPES and f.get("aria-hidden") != "true"
    ]
    if not fields:
        return na("a11y.form_labels", A, "No form fields")
    states = [_has_label(f) for f in fields]
    unlabelled = states.count("")
    placeholder_only = states.count("placeholder")
    value = {"fields": len(fields), "unlabelled": unlabelled, "placeholder_only": placeholder_only}

    def where(state: str) -> list[str]:
        return [f"{css_path(f)} ({f.name}, name={f.get('name') or '-'})" for f, s in zip(fields, states, strict=True) if s == state]

    if unlabelled:
        return result(
            "a11y.form_labels",
            A,
            Status.FAIL,
            f"{unlabelled} of {plural(len(fields), 'form field')} without a label",
            value=value,
            evidence=where("") + where("placeholder"),
        )
    if placeholder_only:
        return result(
            "a11y.form_labels",
            A,
            Status.WARN,
            f"{placeholder_only} form fields are labelled only by placeholder text",
            value=value,
            evidence=where("placeholder"),
        )
    return result("a11y.form_labels", A, Status.PASS, "All form fields have labels", value=value)


def _accessible_name(el: Tag) -> bool:
    if el.get("aria-label", "").strip() or el.get("aria-labelledby") or el.get("title", "").strip():
        return True
    if el.name == "input":
        return bool((el.get("value") or "").strip())
    if el.get_text(strip=True):
        return True
    for img in el.find_all("img"):
        if (img.get("alt") or "").strip():
            return True
    for svg in el.find_all("svg"):
        if svg.find("title") or svg.get("aria-label"):
            return True
    return False


@check("a11y.control_names", A)
def control_names(ctx: ScanContext):
    controls = ctx.dom.find_all("a", href=True) + ctx.dom.find_all("button")
    controls += ctx.dom.find_all("input", attrs={"type": lambda t: t and t.lower() in ("submit", "button")})
    controls = [c for c in controls if c.get("aria-hidden") != "true" and "display:none" not in (c.get("style") or "").replace(" ", "")]
    if not controls:
        return na("a11y.control_names", A, "No links or buttons")
    nameless = [c for c in controls if not _accessible_name(c)]
    count = len(nameless)
    status = Status.PASS
    if count >= ctx.t("control_names_missing_fail"):
        status = Status.FAIL
    elif count >= ctx.t("control_names_missing_warn"):
        status = Status.WARN
    evidence = []
    for c in nameless:
        href = str(c.get("href") or "")
        # Never copy tel:/mailto: targets (contact data); the selector is enough to find them.
        target = "" if href.startswith(("tel:", "mailto:")) else f" → {redact_text(href[:80])}"
        evidence.append(f"{css_path(c)}{target}")
    return result(
        "a11y.control_names",
        A,
        status,
        f"{plural(count, 'link or button', 'links or buttons')} without a readable name (icon only)",
        value=count,
        evidence=evidence,
    )


@check("a11y.lang", A)
def lang(ctx: ScanContext):
    html = ctx.dom.find("html") or ctx.static_dom.find("html")
    value = (html.get("lang") or "").strip() if html else ""
    if value:
        return result("a11y.lang", A, Status.PASS, f"Page language set ({value})", value=value)
    return result("a11y.lang", A, Status.FAIL, "Page language is not declared (<html lang>)", value=None)
