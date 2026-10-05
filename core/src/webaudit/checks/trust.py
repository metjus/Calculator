"""Trust & content checks.

These checks look for contact details but deliberately store only whether
they exist. Phone numbers and e-mail addresses never leave this module.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..context import ScanContext
from ..dom import anchors, class_and_id, normalize_link, same_site, visible_text
from ..models import Area, Status
from . import check, na, plural, result

A = Area.TRUST

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.I)
PHONE_INTL_RE = re.compile(r"(?:\+|00)\s?\d{3}[\s/.-]?\d{2,3}(?:[\s/.-]?\d{2,3}){2,3}\b")
PHONE_SK_MOBILE_RE = re.compile(r"\b09\d{2}[\s/.-]?\d{3}[\s/.-]?\d{3}\b")
PHONE_LOCAL_RE = re.compile(r"\b0?\d{2,3}[\s/.-]?\d{3}[\s/.-]?\d{3,4}\b")
POSTCODE_CITY_RE = re.compile(r"\b\d{3}\s?\d{2}\s+[A-ZÁÄČĎÉÍĽĹŇÓÔŔŠŤÚÝŽŘŮĚ][a-záäčďéíľĺňóôŕšťúýžřůě]{2,}")
YEAR_RE = re.compile(r"(?:©|&copy;|\(c\)|copyright)[^0-9]{0,40}((?:19|20)\d{2})(?:\s*[-–—]\s*((?:19|20)\d{2}))?", re.I)


def has_phone_text(text: str, context_keywords: list[str]) -> bool:
    if PHONE_INTL_RE.search(text) or PHONE_SK_MOBILE_RE.search(text):
        return True
    lowered = text.lower()
    for match in PHONE_LOCAL_RE.finditer(text):
        window = lowered[max(0, match.start() - 30) : match.start()]
        if any(keyword in window for keyword in context_keywords):
            return True
    return False


def _contact_signals(soup: BeautifulSoup | None, ctx: ScanContext) -> dict[str, bool]:
    if soup is None:
        return {"tel_link": False, "mail_link": False, "phone_text": False, "email_text": False}
    hrefs = [(a.get("href") or "").strip().lower() for a in anchors(soup)]
    text = visible_text(soup)
    return {
        "tel_link": any(h.startswith("tel:") and len(re.sub(r"\D", "", h)) >= 6 for h in hrefs),
        "mail_link": any(h.startswith("mailto:") for h in hrefs),
        "phone_text": has_phone_text(text, ctx.signatures["phone_context_keywords"]),
        "email_text": bool(EMAIL_RE.search(text)),
    }


def find_contact_link(soup: BeautifulSoup, base_url: str, keywords: list[str]) -> str | None:
    for a in anchors(soup):
        label = " ".join(a.get_text(" ", strip=True).lower().split())
        href = (a.get("href") or "").lower()
        if any(k in label for k in keywords) or any(f"/{k}" in href for k in ("kontakt", "contact")):
            link = normalize_link(a["href"], base_url)
            if link and same_site(link, base_url):
                return link
    return None


@check("trust.contact", A)
def contact(ctx: ScanContext):
    home = _contact_signals(ctx.dom, ctx)
    page = _contact_signals(ctx.contact_dom, ctx)
    on_home = any(home.values())
    on_page = any(page.values())
    value = {"on_homepage": on_home, "contact_page": ctx.contact_dom is not None, "on_contact_page": on_page}
    if on_home or on_page:
        where = "homepage" if on_home else "contact page"
        return result("trust.contact", A, Status.PASS, f"Phone or e-mail visible on the {where}", value=value)
    if ctx.contact_dom is not None:
        return result("trust.contact", A, Status.WARN, "Contact page exists but shows no phone or e-mail", value=value)
    return result("trust.contact", A, Status.FAIL, "No visible contact details", value=value)


@check("trust.clickable_phone", A)
def clickable_phone(ctx: ScanContext):
    home = _contact_signals(ctx.dom, ctx)
    page = _contact_signals(ctx.contact_dom, ctx)
    tel = home["tel_link"] or page["tel_link"]
    phone_text = home["phone_text"] or page["phone_text"]
    if tel:
        return result("trust.clickable_phone", A, Status.PASS, "Phone number is a tap-to-call link", value=True)
    if phone_text:
        return result("trust.clickable_phone", A, Status.FAIL, "Phone number is shown but not tap-to-call", value=False)
    return na("trust.clickable_phone", A, "No phone number found")


def _host_matches(host: str, rule_host: str) -> bool:
    """``mapy.cz`` matches mapy.cz and its subdomains; ``google.`` matches google.<any TLD> and subdomains."""
    labels = host.lower().strip(".").split(".")
    if rule_host.endswith("."):
        wanted = rule_host.strip(".").split(".")
        # the rule's labels must sit directly before a single top-level label
        return len(labels) > len(wanted) and labels[-1 - len(wanted) : -1] == wanted
    wanted = rule_host.split(".")
    return labels[-len(wanted) :] == wanted


def is_map_url(url: str, rules: list[dict[str, str]]) -> bool:
    parts = urlsplit(url)
    host, path = parts.hostname or "", parts.path or "/"
    return any(_host_matches(host, r["host"]) and path.startswith(r.get("path", "/")) for r in rules)


def _has_map(soup: BeautifulSoup | None, base_url: str, rules: list[dict[str, str]], classes: list[str]) -> bool:
    if soup is None:
        return False
    for tag in soup.find_all(["iframe", "a", "img", "div"]):
        for attr in ("src", "href", "data-src"):
            value = tag.get(attr)
            if value and is_map_url(urljoin(base_url, str(value)), rules):
                return True
        if any(c in class_and_id(tag) for c in classes):
            return True
    return False


def _has_address(soup: BeautifulSoup | None) -> bool:
    if soup is None:
        return False
    if soup.find("address") is not None:
        return True
    if '"postalcode"' in str(soup).lower() or "streetaddress" in str(soup).lower():
        return True
    return bool(POSTCODE_CITY_RE.search(visible_text(soup)))


@check("trust.address_map", A)
def address_map(ctx: ScanContext):
    rules, classes = ctx.signatures["map_links"], ctx.signatures["map_classes"]
    has_map = _has_map(ctx.dom, ctx.final_url, rules, classes) or _has_map(ctx.contact_dom, ctx.final_url, rules, classes)
    has_address = _has_address(ctx.dom) or _has_address(ctx.contact_dom)
    value = {"map": has_map, "address": has_address}
    if has_map:
        return result("trust.address_map", A, Status.PASS, "Map or directions link present", value=value)
    if has_address:
        return result("trust.address_map", A, Status.WARN, "Address shown, but no map or directions link", value=value)
    return result("trust.address_map", A, Status.FAIL, "No address or map found", value=value)


def _footer_text(soup: BeautifulSoup) -> str:
    footers = soup.find_all("footer") or [tag for tag in soup.find_all(["div", "section"]) if "footer" in class_and_id(tag)]
    if footers:
        return " ".join(visible_text(f) for f in footers)
    text = visible_text(soup)
    return text[-1500:]


@check("trust.footer_year", A)
def footer_year(ctx: ScanContext):
    text = _footer_text(ctx.dom)
    years = []
    for match in YEAR_RE.finditer(text):
        years.extend(int(y) for y in match.groups() if y)
    years = [y for y in years if y <= ctx.now.year]
    if not years:
        return na("trust.footer_year", A, "No copyright year in the footer")
    latest = max(years)
    if ctx.now.year - latest > ctx.t("footer_year_max_age"):
        return result("trust.footer_year", A, Status.FAIL, f"Footer says © {latest}; the site may look abandoned", value=latest)
    return result("trust.footer_year", A, Status.PASS, f"Footer year {latest} is current", value=latest)


def social_profiles(ctx: ScanContext) -> dict[str, str]:
    """Map of profile URL -> network for links that point at social profiles."""
    networks: dict[str, list[str]] = ctx.signatures["social"]
    share_patterns = ctx.signatures["social_share_patterns"]
    found: dict[str, str] = {}
    for a in anchors(ctx.dom):
        link = normalize_link(a["href"], ctx.final_url)
        if not link:
            continue
        host = (urlsplit(link).hostname or "").lower()
        for network, domains in networks.items():
            if any(host == d or host.endswith("." + d) for d in domains):
                if not any(p in link.lower() for p in share_patterns):
                    found[link] = network
    return found


@check("trust.social_links", A)
def social_links(ctx: ScanContext):
    profiles = social_profiles(ctx)
    if not profiles:
        return na("trust.social_links", A, "No social network links")
    generic = [u for u in profiles if urlsplit(u).path in ("", "/")]
    broken = [u for u in profiles if (ctx.link_results.get(u) or (None, None))[0] in (404, 410)]
    networks = sorted(set(profiles.values()))
    value = {"networks": networks, "generic": len(generic), "broken": len(broken)}
    if generic or broken:
        return result(
            "trust.social_links",
            A,
            Status.FAIL,
            f"{plural(len(generic) + len(broken), 'social icon')} leading nowhere useful",
            value=value,
            evidence=generic + broken,
        )
    return result("trust.social_links", A, Status.PASS, f"Social links: {', '.join(networks)}", value=value)


def _matches_any(haystack: str, needles: list[str]) -> list[str]:
    lowered = haystack.lower()
    return [n for n in needles if n.lower() in lowered]


@check("trust.cookie_banner", A)
def cookie_banner(ctx: ScanContext):
    sources = " ".join(str(s.get("src") or "") + " " + (s.string or "")[:3000] for s in ctx.static_dom.find_all("script"))
    sources += " " + " ".join(r.get("url", "") for r in ctx.all_requests())
    trackers = sorted(set(_matches_any(sources, ctx.signatures["trackers"])))
    cmp = sorted(set(_matches_any(sources + " " + str(ctx.dom)[:400_000], ctx.signatures["consent_managers"])))
    rendered_banner = any(bool(r.cookie.get("detected")) for r in (ctx.desktop, ctx.mobile) if r and r.ok)
    value = {"trackers": trackers, "consent_manager": cmp, "banner_seen": rendered_banner}
    if cmp or rendered_banner:
        return result("trust.cookie_banner", A, Status.PASS, "Cookie consent banner present", value=value)
    if trackers:
        return result(
            "trust.cookie_banner", A, Status.FAIL, f"Tracking ({', '.join(trackers[:3])}) without a cookie consent banner", value=value
        )
    return na("trust.cookie_banner", A, "No tracking detected, banner not required")


@check("trust.broken_links", A)
def broken_links(ctx: ScanContext):
    internal = {u: r for u, r in ctx.link_results.items() if same_site(u, ctx.final_url)}
    checked = {u: r for u, r in internal.items() if r[1] != "robots"}
    if not checked:
        return na("trust.broken_links", A, "No internal links checked")
    broken = [
        u
        for u, (status, error) in checked.items()
        if (status is not None and (status in (404, 410) or status >= 500)) or (status is None and error and "blocked" not in error)
    ]
    status = Status.PASS
    if len(broken) >= ctx.t("broken_links_fail"):
        status = Status.FAIL
    elif len(broken) >= ctx.t("broken_links_warn"):
        status = Status.WARN
    return result(
        "trust.broken_links",
        A,
        status,
        f"{len(broken)} of {plural(len(checked), 'checked link')} broken",
        value={"broken": len(broken), "checked": len(checked)},
        evidence=[urlsplit(u).path or u for u in broken],
    )
