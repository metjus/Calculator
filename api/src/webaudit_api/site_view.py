"""What the operator UI shows about one scanned website, derived from its stored ScanResult.

Score by area, problems with their place on the page, the key facts at a glance and a
summary of what the homepage contains. Everything here is computed from the stored result,
so older audits get the same view. Labels are English (the operator UI language).
"""

from __future__ import annotations

from typing import Any

from webaudit import Config, Status
from webaudit.report import area_label, issue_text

Tone = str  # "bad" | "warn" | "ok"


def checks_by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in result.get("checks") or []}


def areas(result: dict[str, Any], config: Config) -> list[dict[str, Any]]:
    """Every scoring area in config order, with its score (None = not used for this site) and weight in %."""
    spec = config.scoring["areas"]
    total_weight = sum(a["weight"] for a in spec.values()) or 1
    scored = {a["area"]: a for a in (result.get("score") or {}).get("areas") or []}
    return [
        {
            "area": area,
            "label": area_label(config, area),
            "score": scored[area]["score"] if area in scored else None,
            "weight": round(spec[area]["weight"] / total_weight * 100),
        }
        for area in spec
    ]


def problems(result: dict[str, Any], config: Config) -> list[dict[str, Any]]:
    """Issues by impact, each with the English client text and the evidence (where on the page)."""
    checks = checks_by_id(result)
    out = []
    for issue in result.get("issues") or []:
        check = checks.get(issue["check_id"], {})
        status = Status(issue["status"])
        text = issue_text(config, issue["check_id"], "en", status) or {}
        out.append(
            {
                **issue,
                "area_label": area_label(config, issue["area"]),
                "label": text.get("label", issue["check_id"]),
                "problem": text.get("problem", ""),
                "solution": text.get("solution", ""),
                "summary": check.get("summary", ""),
                "where": list(check.get("evidence") or [])[:8],
            }
        )
    return out


def _size(n: float) -> str:
    return f"{n / 1_000_000:.1f} MB" if n >= 1_000_000 else f"{round(n / 1000)} kB"


def _tone(status: str | None) -> Tone:
    return {"pass": "ok", "warn": "warn", "fail": "bad"}.get(status or "", "ok")


def facts(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Key facts at a glance; facts that were not measured are left out."""
    checks = checks_by_id(result)
    out: list[dict[str, Any]] = []

    def add(label: str, value: str, tone: Tone) -> None:
        out.append({"label": label, "value": value, "tone": tone})

    def status(check_id: str) -> str | None:
        return (checks.get(check_id) or {}).get("status")

    def value(check_id: str) -> Any:
        return (checks.get(check_id) or {}).get("value")

    if status("basics.https") == "fail":
        add("Secure connection", "No HTTPS", "bad")
    elif status("basics.https") == "pass":
        ssl = status("basics.ssl_valid")
        add(
            "Secure connection",
            "HTTPS, certificate problem" if ssl == "fail" else "HTTPS, valid certificate",
            "bad" if ssl == "fail" else "ok",
        )
    if status("basics.http_redirect") in ("pass", "warn", "fail"):
        add("http → https redirect", "Yes" if status("basics.http_redirect") == "pass" else "No", _tone(status("basics.http_redirect")))
    if status("mobile.viewport") in ("pass", "fail"):
        add("Mobile layout", "Yes" if status("mobile.viewport") == "pass" else "No", _tone(status("mobile.viewport")))
    tech = result.get("tech") or {}
    if tech.get("cms"):
        outdated = status("tech.cms_version") == "fail"
        name = " ".join(p for p in (tech["cms"], tech.get("cms_version")) if p)
        add("Content system", f"{name}, outdated" if outdated else name, "warn" if outdated else "ok")
    else:
        add("Content system", "Not detected", "ok")
    mobile, desktop = value("speed.pagespeed_mobile"), value("speed.pagespeed_desktop")
    if mobile is not None or desktop is not None:
        worst = min(v for v in (mobile, desktop) if v is not None)
        add(
            "PageSpeed mobile / desktop",
            f"{mobile if mobile is not None else '—'} / {desktop if desktop is not None else '—'}",
            "bad" if worst < 50 else "warn" if worst < 90 else "ok",
        )
    else:
        add("PageSpeed", "Not measured (no key)", "ok")
    vitals = value("speed.core_web_vitals") or {}
    if vitals.get("lcp_ms") is not None:
        add("Main content shown (LCP)", f"{vitals['lcp_ms'] / 1000:.1f} s", _tone(status("speed.core_web_vitals")))
    if value("speed.page_weight") is not None:
        add("Page weight", _size(value("speed.page_weight")), _tone(status("speed.page_weight")))
    if value("speed.server_response") is not None:
        add("Server response", f"{value('speed.server_response'):.2f} s", _tone(status("speed.server_response")))
    old = [lib for lib in value("tech.outdated_libraries") or [] if lib.get("status") in ("warn", "fail")]
    if old:
        add("Old components", ", ".join(f"{lib['name']} {lib.get('version') or ''}".strip() for lib in old[:3]), "warn")
    if status("trust.cookie_banner") in ("pass", "warn", "fail"):
        add(
            "Cookie consent",
            "OK" if status("trust.cookie_banner") == "pass" else "Trackers without consent",
            _tone(status("trust.cookie_banner")),
        )
    return out


def page_contents(result: dict[str, Any]) -> list[dict[str, str]]:
    """A short summary of the homepage inventory (already redacted when it was stored)."""
    inv = result.get("inventory") or {}
    if not inv:
        return []
    meta = inv.get("meta") or {}
    levels: dict[int, int] = {}
    for heading in inv.get("headings") or []:
        levels[heading.get("level", 0)] = levels.get(heading.get("level", 0), 0) + 1
    images = inv.get("images") or []
    no_alt = sum(1 for img in images if not img.get("alt"))
    forms = inv.get("forms") or []
    links = inv.get("links") or {}
    social = (checks_by_id(result).get("trust.social_links") or {}).get("value") or {}
    rows = [
        ("Title", meta.get("title") or "Missing"),
        ("Search description", meta.get("description") or "Missing"),
        ("Headings", " · ".join(f"H{level} × {count}" for level, count in sorted(levels.items()) if level) or "None"),
        ("Images", f"{len(images)}" + (f" · {no_alt} without a description" if no_alt else "")),
        ("Forms", str(len(forms))),
        (
            "Links",
            f"{links.get('internal_count', len(links.get('internal') or []))} internal · {links.get('external_count', len(links.get('external') or []))} external",
        ),
        ("Language", meta.get("lang") or "Not set"),
        ("Social links", ", ".join(n.capitalize() for n in social.get("networks") or []) or "None"),
    ]
    return [{"label": label, "value": str(value)[:160]} for label, value in rows]


def comparison(result: dict[str, Any] | None) -> dict[str, Any]:
    """The few facts the competitor table compares: mobile layout, HTTPS, PageSpeed and area scores."""
    checks = checks_by_id(result or {})

    def passed(check_id: str) -> bool | None:
        status = (checks.get(check_id) or {}).get("status")
        return None if status in (None, "na") else status == "pass"

    return {
        "mobile": passed("mobile.viewport"),
        "https": passed("basics.https"),
        "pagespeed": (checks.get("speed.pagespeed_mobile") or {}).get("value"),
        "areas": {a["area"]: a["score"] for a in ((result or {}).get("score") or {}).get("areas") or []},
    }
