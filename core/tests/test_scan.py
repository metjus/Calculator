"""End-to-end scans against the local fixture websites."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from conftest import needs_browser

from webaudit import Config, Scanner, SiteState, Status
from webaudit.netguard import NetGuard
from webaudit.scanner import ProgressEvent

FAST = {
    "scanner": {
        "politeness": {"min_delay_between_requests_s": 0.0},
        "limits": {"max_external_links_checked": 0},
        "timeouts": {"site_total_s": 60, "navigation_s": 20},
        "browser": {"network_idle_wait_ms": 500},
    }
}


def _statuses(result) -> dict[str, Status]:
    return {c.id: c.status for c in result.checks}


async def _scan(sites, trusted_transport, names, *, browser: bool, events=None):
    config = Config.load(overrides=FAST)
    async with Scanner(
        config,
        use_browser=browser,
        allow_private=True,
        transport=trusted_transport,
        on_event=(events.append if events is not None else None),
    ) as scanner:
        if browser and scanner.browser is None:
            pytest.skip(f"browser unavailable: {scanner.browser_error}")
        return await scanner.scan_many([sites.urls[n] for n in names], concurrency=4)


async def test_static_scan_modern_vs_legacy(sites, trusted_transport) -> None:
    events: list[ProgressEvent] = []
    modern, legacy = await _scan(sites, trusted_transport, ["modern", "legacy"], browser=False, events=events)

    assert modern.state is SiteState.OK, modern.state_reason
    assert legacy.state is SiteState.OK, legacy.state_reason
    m, leg = _statuses(modern), _statuses(legacy)

    # Basics: the modern fixture runs on HTTPS with a trusted certificate.
    assert m["basics.https"] is Status.PASS and m["basics.ssl_valid"] is Status.PASS
    assert leg["basics.https"] is Status.FAIL and leg["basics.ssl_valid"] is Status.NA

    # SEO
    for check_id in (
        "seo.title",
        "seo.meta_description",
        "seo.h1",
        "seo.sitemap",
        "seo.open_graph",
        "seo.favicon",
        "seo.structured_data",
        "seo.indexable",
        "seo.canonical",
    ):
        assert m[check_id] is Status.PASS, check_id
    assert leg["seo.title"] is Status.WARN  # generic "Home"
    assert leg["seo.meta_description"] is Status.FAIL and leg["seo.h1"] is Status.FAIL
    assert leg["seo.structured_data"] is Status.FAIL and leg["seo.sitemap"] is Status.FAIL
    assert leg["seo.canonical"] is Status.WARN  # no canonical at all is a warning, not a failure
    # Both fixtures are short pages, so both are thin; the check still has to say how short.
    thin = next(c for c in legacy.checks if c.id == "seo.thin_content")
    assert leg["seo.thin_content"] is Status.FAIL and thin.value["words"] > 0

    # Trust
    assert m["trust.contact"] is Status.PASS and m["trust.clickable_phone"] is Status.PASS
    assert m["trust.address_map"] is Status.PASS and m["trust.footer_year"] is Status.PASS
    assert leg["trust.clickable_phone"] is Status.FAIL  # "Tel: 0905 123 456" without tel: link
    assert leg["trust.footer_year"] is Status.FAIL  # © 2012
    assert leg["trust.social_links"] is Status.FAIL  # icon pointing at facebook.com/
    assert leg["trust.cookie_banner"] is Status.FAIL  # analytics without consent
    assert leg["trust.broken_links"] is Status.WARN  # /stara-stranka is a 404
    assert m["trust.broken_links"] is Status.PASS

    # Tech / design / accessibility (static parts)
    assert leg["tech.outdated_libraries"] is Status.FAIL
    assert legacy.tech.libraries[0].name == "jQuery" and legacy.tech.libraries[0].version == "1.8.3"
    assert leg["design.table_layout"] is Status.FAIL and leg["design.legacy_markup"] is Status.FAIL
    assert m["design.table_layout"] is Status.PASS and m["design.legacy_markup"] is Status.PASS
    assert leg["mobile.viewport"] is Status.FAIL and m["mobile.viewport"] is Status.PASS
    assert leg["a11y.img_alt"] is Status.FAIL and m["a11y.img_alt"] is Status.PASS
    assert leg["a11y.form_labels"] is Status.FAIL and m["a11y.form_labels"] is Status.PASS
    assert leg["a11y.control_names"] is Status.WARN
    assert leg["a11y.lang"] is Status.FAIL and m["a11y.lang"] is Status.PASS
    assert leg["speed.large_images"] is Status.WARN  # 400 KB logo.gif via HEAD

    # Browser-only checks are skipped, not failed.
    for check_id in ("mobile.font_size", "a11y.contrast", "design.font_count", "tech.console_errors"):
        assert m[check_id] is Status.NA and leg[check_id] is Status.NA

    assert modern.score.total > 80 > 40 > legacy.score.total
    assert legacy.issues[0].impact >= legacy.issues[-1].impact

    # Contact details never end up in results.
    dumped = modern.model_dump_json() + legacy.model_dump_json()
    assert "0905" not in dumped and "info@lena-example.sk" not in dumped

    assert any(e.step == "loading homepage" for e in events)
    assert sum(1 for e in events if e.step == "done") == 2


async def test_protected_robots_and_unreachable(sites, trusted_transport) -> None:
    config = Config.load(overrides=FAST)
    async with Scanner(config, use_browser=False, allow_private=True, transport=trusted_transport) as scanner:
        cloudflare, robots, down, invalid = await scanner.scan_many(
            [sites.urls["cloudflare"], sites.urls["robots"], "http://127.0.0.9:9/", "not a url"]
        )
    assert cloudflare.state is SiteState.PROTECTED
    assert cloudflare.state_reason == "Probably protected by Cloudflare – check manually"
    assert cloudflare.score is None and cloudflare.protection.provider == "cloudflare"
    assert robots.state is SiteState.DISALLOWED and robots.score is None
    assert down.state is SiteState.UNREACHABLE and down.score is None and down.state_reason
    assert invalid.state is SiteState.INVALID


async def test_private_targets_refused_by_default() -> None:
    async with Scanner(use_browser=False) as scanner:
        result = await scanner.scan("http://127.0.0.1:1/")
    assert result.state is SiteState.INVALID
    assert "private" in result.state_reason


@needs_browser
async def test_browser_scan_measures_rendered_page(sites, trusted_transport, tmp_path) -> None:
    config = Config.load(overrides=FAST)
    async with Scanner(config, allow_private=True, transport=trusted_transport, screenshots_dir=tmp_path) as scanner:
        if scanner.browser is None:
            pytest.skip(f"browser unavailable: {scanner.browser_error}")
        modern, legacy = await scanner.scan_many([sites.urls["modern"], sites.urls["legacy"]], concurrency=2)

    m, leg = _statuses(modern), _statuses(legacy)
    assert m["mobile.font_size"] is Status.PASS
    assert leg["mobile.font_size"] is Status.FAIL  # no viewport + 11px text
    assert m["mobile.horizontal_scroll"] is Status.PASS
    assert leg["design.fixed_width"] is Status.FAIL and m["design.fixed_width"] is Status.PASS
    assert leg["design.font_count"] in (Status.WARN, Status.FAIL)
    assert leg["a11y.contrast"] is Status.FAIL  # #aaa on white
    assert m["a11y.contrast"] is Status.PASS
    assert m["tech.console_errors"] is Status.PASS
    assert m["speed.page_weight"] is Status.PASS
    assert {"desktop", "mobile"} <= set(modern.screenshots)
    for path in modern.screenshots.values():
        assert (tmp_path / path.split("/")[-1]).exists()
    assert modern.score.total > legacy.score.total + 30


@needs_browser
async def test_browser_cannot_reach_internal_hosts(sites) -> None:
    """Redirects, WebSockets and fetches from a hostile page must not reach private addresses."""
    guard = NetGuard(is_public=lambda ip: ip != "127.0.0.6")  # treat only the "internal" server as private
    async with Scanner(Config.load(overrides=FAST), guard=guard) as scanner:
        if scanner.browser is None:
            pytest.skip(f"browser unavailable: {scanner.browser_error}")
        result = await scanner.scan(sites.urls["attacker"])
    assert result.state is SiteState.OK, result.state_reason
    assert "/redir-frame" in sites.hits["attacker"]  # the browser really rendered the page
    assert sites.hits["internal"] == []


async def test_a_browser_that_does_not_start_in_time_is_skipped(monkeypatch, sites, trusted_transport) -> None:
    """A hanging browser start would hang the audit (and, in the desktop app, the whole queue)."""

    async def never(self) -> None:  # noqa: ANN001
        await asyncio.sleep(30)

    monkeypatch.setattr("webaudit.browser.Browser.start", never)
    timeouts = {**FAST["scanner"]["timeouts"], "browser_start_s": 0.2}
    config = Config.load(overrides={"scanner": {**FAST["scanner"], "timeouts": timeouts}})
    async with Scanner(config, allow_private=True, transport=trusted_transport) as scanner:
        assert scanner.browser is None and "did not start in time" in scanner.browser_error
        result = await scanner.scan(sites.urls["legacy"])
    assert result.state is SiteState.OK and result.score is not None  # scored from the static checks
    assert any("browser checks skipped" in entry.message for entry in result.log)


@needs_browser
async def test_a_cookie_bar_that_navigates_away_does_not_decide_what_we_measure(sites, trusted_transport, tmp_path) -> None:
    """Whatever the consent button does, the screenshot and the metrics belong to the audited page."""
    config = Config.load(overrides=FAST)
    base = sites.urls["modern"].rstrip("/")
    async with Scanner(config, allow_private=True, transport=trusted_transport) as scanner:
        if scanner.browser is None:
            pytest.skip(f"browser unavailable: {scanner.browser_error}")
        link = await scanner.browser.render(f"{base}/cookie-link", mobile=False, screenshot_path=tmp_path / "link.jpg")
        jump = await scanner.browser.render(f"{base}/cookie-jump", mobile=False, screenshot_path=tmp_path / "jump.jpg")

    # A button wrapped in a link is never pressed: closing the bar is not worth leaving the page for.
    assert link.ok and link.cookie["detected"] and link.cookie["dismissed"] is False and link.cookie["method"] is None
    # One that navigates from JavaScript cannot be seen in advance, so the scanner comes back.
    assert jump.ok and jump.cookie.get("left_page") is True and jump.cookie["dismissed"] is False
    for data in (link, jump):
        assert data.cookie["hidden"] is True  # taken off the screen instead of clicked away
        assert 'id="trap"' in data.html  # measured this page, not the one the click led to
        assert "Služby" not in (data.html or "")
        assert Path(data.screenshot).stat().st_size > 1000
