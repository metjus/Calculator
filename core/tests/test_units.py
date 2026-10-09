"""Pure unit tests: robots parser, inputs, scoring, net guard, protection, texts."""

from __future__ import annotations

import pytest

from webaudit import Config
from webaudit.checks import seo
from webaudit.context import ScanContext
from webaudit.dom import parse
from webaudit.fetch import Fetch
from webaudit.inputs import normalize_url, parse_csv_text
from webaudit.models import Area, Category, CheckResult, Status
from webaudit.netguard import BlockedTarget, NetGuard, is_public_ip
from webaudit.protection import detect
from webaudit.report import issue_text
from webaudit.robots import Robots
from webaudit.scoring import rank_issues, score
from webaudit.techdetect import version_below

# ----------------------------------------------------------------- robots


def test_robots_longest_match_and_wildcards() -> None:
    robots = Robots("User-agent: *\nDisallow: /private/\nAllow: /private/public\nDisallow: /*.pdf$\nSitemap: https://x.sk/sitemap.xml\n")
    assert robots.can_fetch("WebAuditBot", "/")
    assert not robots.can_fetch("WebAuditBot", "/private/a")
    assert robots.can_fetch("WebAuditBot", "/private/public/page")
    assert not robots.can_fetch("WebAuditBot", "/files/cennik.pdf")
    assert robots.can_fetch("WebAuditBot", "/files/cennik.pdf?x=1")
    assert robots.sitemaps == ["https://x.sk/sitemap.xml"]


def test_robots_specific_group_wins_and_crawl_delay() -> None:
    robots = Robots("User-agent: *\nDisallow: /\n\nUser-agent: WebAuditBot\nUser-agent: other\nAllow: /\nCrawl-delay: 3\n")
    assert robots.can_fetch("WebAuditBot/0.1", "/anything")
    assert not robots.can_fetch("SomeOtherBot", "/anything")
    assert robots.crawl_delay("WebAuditBot") == 3
    assert not Robots("User-agent: WebAuditBot/1.0\nDisallow: /\n").can_fetch("WebAuditBot/0.1 (+x)", "/")


def test_robots_disallow_all_and_empty() -> None:
    assert not Robots(disallow_all=True).can_fetch("WebAuditBot", "/")
    assert Robots("").can_fetch("WebAuditBot", "/")
    assert Robots("User-agent: *\nDisallow:\n").can_fetch("WebAuditBot", "/x")


# ----------------------------------------------------------------- inputs


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("kadernictvo-x.sk", "https://kadernictvo-x.sk/"),
        ("  HTTP://Example.SK/cennik?x=1#top ", "http://example.sk/cennik?x=1"),
        ("kaderníctvo.sk", "https://" + "kaderníctvo".encode("idna").decode() + ".sk/"),
        ("https://example.sk:8443", "https://example.sk:8443/"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "ftp://x.sk", "not a domain", "https://"])
def test_normalize_url_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_url(raw)


def test_csv_semicolon_no_website_and_competitors() -> None:
    text = (
        "url;názov firmy;konkurencia;projekt\n"
        'kadernictvo-x.sk;Kaderníctvo X;"a.sk, b.sk";Kaderníctva Trnava\n'
        ";Salón bez webu;;Kaderníctva Trnava\n"
        "zle url;Firma Y;;Kaderníctva Trnava\n"
    )
    rows = parse_csv_text(text)
    assert [r.company for r in rows] == ["Kaderníctvo X", "Salón bez webu", "Firma Y"]
    assert rows[0].url == "https://kadernictvo-x.sk/"
    assert rows[0].competitors == ["https://a.sk/", "https://b.sk/"]
    assert rows[0].project == "Kaderníctva Trnava"
    assert rows[1].url is None and not rows[1].has_website and rows[1].error is None
    assert rows[2].error and rows[2].url is None


def test_csv_requires_known_columns() -> None:
    with pytest.raises(ValueError):
        parse_csv_text("foo,bar\n1,2\n")


# ---------------------------------------------------------------- scoring


def _check(check_id: str, area: Area, status: Status) -> CheckResult:
    return CheckResult(id=check_id, area=area, status=status)


def test_score_ignores_na_and_renormalises() -> None:
    config = Config.load()
    checks = [
        _check("basics.https", Area.BASICS, Status.PASS),
        _check("basics.ssl_valid", Area.BASICS, Status.PASS),
        _check("basics.http_redirect", Area.BASICS, Status.NA),
        _check("mobile.viewport", Area.MOBILE, Status.FAIL),
    ]
    result = score(checks, config.scoring)
    assert result is not None
    by_area = {a.area: a.score for a in result.areas}
    assert by_area == {Area.BASICS: 100, Area.MOBILE: 0}
    # Only basics (16) and mobile (20) are present: 100*16/36 = 44.4
    assert result.total == 44
    assert result.category is Category.WEAK
    assert {a.area for a in result.areas} == {Area.BASICS, Area.MOBILE}  # design_ai etc. excluded


def test_score_none_when_nothing_evaluated() -> None:
    assert score([_check("basics.https", Area.BASICS, Status.NA)], Config.load().scoring) is None


def test_categories_follow_config_thresholds() -> None:
    config = Config.load(overrides={"scoring": {"categories": [{"id": "critical", "min": 0}, {"id": "good", "min": 50}]}})
    result = score([_check("basics.https", Area.BASICS, Status.WARN)], config.scoring)
    assert result.total == 50 and result.category is Category.GOOD


def test_rank_issues_orders_by_cost() -> None:
    config = Config.load()
    checks = [
        _check("seo.favicon", Area.SEO, Status.FAIL),
        _check("seo.title", Area.SEO, Status.PASS),
        _check("mobile.viewport", Area.MOBILE, Status.FAIL),
        _check("mobile.font_size", Area.MOBILE, Status.WARN),
    ]
    issues = rank_issues(checks, config.scoring)
    assert [i.check_id for i in issues] == ["mobile.viewport", "mobile.font_size", "seo.favicon"]
    assert all(i.impact > 0 for i in issues)
    total = score(checks, config.scoring).total
    assert abs((100 - total) - sum(i.impact for i in issues)) <= 1.5


# --------------------------------------------------------------- netguard


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "100.64.0.1", "0.0.0.0", "::ffff:127.0.0.1"]
)
def test_private_ips_are_not_public(ip: str) -> None:
    assert not is_public_ip(ip)


def test_public_ip() -> None:
    assert is_public_ip("93.184.216.34")


async def test_guard_blocks_private_targets() -> None:
    guard = NetGuard()
    for url in (
        "http://127.0.0.1/",
        "http://localhost:8080/",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "http://user:pw@example.sk/",
    ):
        with pytest.raises(BlockedTarget):
            await guard.check_url(url)
    await NetGuard(allow_private=True).check_url("http://127.0.0.1:9/")


# ------------------------------------------------------------- protection


def test_cloudflare_challenge_detected() -> None:
    sigs = Config.load().signatures
    found = detect(403, {"server": "cloudflare", "cf-ray": "1"}, "<title>Just a moment...</title>", sigs)
    assert found and found.provider == "cloudflare"
    found_200 = detect(
        200, {"server": "cloudflare", "cf-ray": "1"}, "<title>Just a moment...</title><div id=challenge-platform></div>", sigs
    )
    assert found_200 and found_200.provider == "cloudflare"


def test_normal_cloudflare_site_not_flagged() -> None:
    sigs = Config.load().signatures
    assert detect(200, {"server": "cloudflare", "cf-ray": "1"}, "<html><h1>Kaderníctvo</h1></html>", sigs) is None
    assert detect(404, {"server": "nginx"}, "<h1>Not found</h1>", sigs) is None


# ------------------------------------------------------------ texts/misc


def test_every_scored_check_has_texts_in_all_languages() -> None:
    config = Config.load()
    for area in config.scoring["areas"].values():
        for check_id in area["checks"]:
            for lang in ("sk", "cs", "en"):
                text = issue_text(config, check_id, lang)
                assert text and all(text.get(k) for k in ("label", "problem", "impact", "solution")), (check_id, lang)


def test_warn_variant_overrides_problem_text() -> None:
    config = Config.load()
    fail = issue_text(config, "mobile.viewport", "sk", Status.FAIL)
    warn = issue_text(config, "mobile.viewport", "sk", Status.WARN)
    assert fail["label"] == warn["label"] and fail["problem"] != warn["problem"]
    assert "warn" not in fail


def test_config_override_dir(tmp_path) -> None:
    (tmp_path / "scoring.json").write_text('{"areas": {"mobile": {"weight": 99}}}', "utf-8")
    config = Config.load(tmp_path)
    assert config.scoring["areas"]["mobile"]["weight"] == 99
    assert "mobile.viewport" in config.scoring["areas"]["mobile"]["checks"]  # deep merge kept the rest


def test_version_compare() -> None:
    assert version_below("1.12.4", "3.5.0")
    assert not version_below("3.7.1", "3.5.0")
    assert version_below("6.4", "6.4.1")
    assert not version_below("10", "10")


def test_normal_cloudflare_page_with_bot_script_not_flagged() -> None:
    sigs = Config.load().signatures
    page = '<html><h1>Kaderníctvo</h1><script src="/cdn-cgi/challenge-platform/h/b/scripts/jsd/main.js"></script></html>'
    assert detect(200, {"server": "cloudflare", "cf-ray": "1"}, page, sigs) is None
    assert detect(403, {"server": "cloudflare", "cf-ray": "1"}, page, sigs) is not None


def test_map_links_match_host_not_substring() -> None:
    from webaudit.checks.trust import is_map_url

    rules = Config.load().signatures["map_links"]
    for url in (
        "https://www.google.com/maps/embed?pb=1",
        "https://www.google.sk/maps/place/Trnava",
        "https://maps.google.cz/?q=Brno",
        "https://maps.app.goo.gl/abc",
        "https://mapy.cz/s/xyz",
        "https://en.mapy.cz/zakladni",
    ):
        assert is_map_url(url, rules), url
    for url in ("https://elsewhere.com/x", "https://www.google.com/search?q=maps", "https://notmapy.cz/", "https://google.evil.com/maps"):
        assert not is_map_url(url, rules), url


def _seo_ctx(html: str, url: str = "https://salon.sk/") -> ScanContext:
    """The smallest context the SEO checks need: a fetched page and its DOM."""
    dom = parse(html)
    return ScanContext(
        config=Config.load(),
        url=url,
        home=Fetch(url=url, final_url=url, status=200, _text=html),
        dom=dom,
        static_dom=dom,
        robots=Robots.allow_all(),
    )


def test_canonical_pointing_away_is_a_failure_but_a_missing_one_is_not() -> None:
    """A homepage canonicalised to another page asks Google to list that page instead."""
    away = seo.canonical(_seo_ctx('<html><head><link rel="canonical" href="https://inde.sk/vitajte"></head><body></body></html>'))
    assert away.status is Status.FAIL and "inde.sk" in away.summary and away.evidence

    home = seo.canonical(_seo_ctx('<html><head><link rel="canonical" href="/"></head><body></body></html>'))
    assert home.status is Status.PASS

    assert seo.canonical(_seo_ctx("<html><head></head><body></body></html>")).status is Status.WARN


def test_thin_content_counts_the_words_a_visitor_can_read() -> None:
    config = Config.load()
    warn, fail = config.scanner["thresholds"]["homepage_words_warn"], config.scanner["thresholds"]["homepage_words_fail"]

    def page(words: int) -> str:
        return f"<html><body><p>{' '.join(['slovo'] * words)}</p><script>var ignored = 'this is not read';</script></body></html>"

    assert seo.thin_content(_seo_ctx(page(fail - 10))).status is Status.FAIL
    assert seo.thin_content(_seo_ctx(page(warn - 10))).status is Status.WARN
    full = seo.thin_content(_seo_ctx(page(warn + 50)))
    assert full.status is Status.PASS and full.value["words"] >= warn
