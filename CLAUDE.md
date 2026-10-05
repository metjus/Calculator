# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A website-audit SaaS for web designers (brief in Slovak: `docs/SPEC.sk.md`; SaaS translation and stage plan: `docs/ARCHITECTURE.md`). The brief is built **in stages, showing the user each result before continuing**; check the stage table in `docs/ARCHITECTURE.md` before starting new work. The brief also requires showing UI design proposals before writing any UI code.

Only `core/` exists so far (stage 1). `api/` (FastAPI) and `web/` (React SPA) come in stage 2.

## Commands (run from `core/`)

```bash
python -m venv ../.venv && ../.venv/bin/pip install -e ".[dev]"   # dev deps incl. playwright, trustme
../.venv/bin/pytest                                   # all tests (~5 s)
../.venv/bin/pytest tests/test_units.py -k robots     # a subset
../.venv/bin/pytest tests/test_scan.py::test_static_scan_modern_vs_legacy
../.venv/bin/webaudit scan example.sk --lang sk       # CLI; --no-browser, --csv, --json, --screenshots DIR
../.venv/bin/ruff check src tests && ../.venv/bin/ruff format --check src tests   # lint + format (config in pyproject)
```

Cloud sessions run `.claude/hooks/session-start.sh`, which creates `/home/user/Calculator/.venv` (repo-root `.venv`), installs `core[dev]` and exports `WEBAUDIT_CHROMIUM_PATH`.

- Browser checks need Chromium. In cloud containers Playwright's own browser is not installed; set `WEBAUDIT_CHROMIUM_PATH=/opt/pw-browsers/chromium` (`tests/conftest.py` does this automatically). Browser tests skip when Chromium is missing.
- These containers usually have no general internet access. Use the local fixture sites instead of real websites: `python tests/serve_fixtures.py /tmp/fx` serves them and writes `ca.pem` and `urls.txt`; then run `SSL_CERT_FILE=/tmp/fx/ca.pem webaudit scan --allow-private $(cat /tmp/fx/urls.txt)`.
- `--allow-private` disables the SSRF guard. Use it only for local testing.

## Core architecture (`core/src/webaudit`)

Data flow for one site (`scanner.py`, `Scanner._scan`):

1. **Gather**: does all I/O.
   - `fetch.PoliteClient` follows redirects manually so every hop passes `netguard.NetGuard` (SSRF) and robots.txt (`robots.py`, our own RFC 9309 parser with wildcards). It paces requests per host via an injectable `RateLimiter`.
   - `protection.detect` turns Cloudflare/WAF blocks into state `protected`.
   - Site files (sitemap, favicon, contact page) and link checks are fetched.
   - `browser.Browser` (Playwright) renders desktop and mobile views and runs JS measurement snippets (fonts, contrast, tap targets, layout, libraries, oversized images). It also closes cookie bars first. Links, browser and PageSpeed run concurrently under the per-site time budget.
2. **Check**: everything lands in `context.ScanContext`.
   - Checks in `checks/*.py` are **pure functions** `(ScanContext) -> CheckResult`, registered with `@check(id, area)`, and must never do I/O.
   - `checks.run_all` turns a crashing check into status `na` plus a log line, so one bug never kills a scan.
   - Browser-dependent checks return `na` when `ctx.desktop` / `ctx.mobile` are missing.
3. **Score**:
   - `scoring.score` takes area-weighted means over non-`na` checks, re-normalising over the areas present (e.g. no PageSpeed key, no AI review). It returns `None` → the site is not scored.
   - `scoring.rank_issues` orders warn/fail checks by points of total score lost.

Invariants that span files:

- **A check id must be listed in three places:** its `@check(...)` decorator, `defaults/scoring.json` (area + weight; unlisted checks are informational) and `defaults/texts.json` (SK/CS/EN `label/problem/impact/solution`, optional `warn` override). `tests/test_units.py` asserts the texts exist.
- **SSRF boundary:** user URLs go through `NetGuard.check_url` on every httpx hop; Chromium is launched with `egress.GuardedProxy` as its proxy (the route handler is only a fast-fail — Playwright doesn't route redirect hops or WebSockets). Never launch a browser or HTTP client that bypasses these. `test_browser_cannot_reach_internal_hosts` must keep passing.
- **Contact data is never stored.** Trust checks record only booleans/counts; evidence lists must not contain phone numbers or e-mails, and the e2e test asserts this.
- **Thresholds and weights live in `defaults/*.json`, not in code.** Read them through `ctx.t(name)` (scanner thresholds) and `ctx.signatures` (CMS/library/tracker/firewall patterns). Users override them with a config dir and the SaaS with per-workspace dicts, both deep-merged by `Config.load`.
- **Sites without a score have a `SiteState` and reason.** The states are `unreachable`, `protected`, `disallowed`, `invalid` and `cancelled`. These sites are excluded from statistics.
- **Progress for the UI** flows through `ProgressEvent` (`on_event` callback): `step` events, log events with levels ok/warn/error, and a final `done` event carrying the `ScanResult`.
- **UI language is English;** client-facing text (texts.json, future PDFs) is SK/CS/EN, in formal address, hedged wording, with no invented numbers.

## Tests

`tests/sites.py` defines the fixture websites:
- `modern` is served over HTTPS with a trustme CA.
- `legacy` is a 2010-style site.
- `cloudflare` returns a challenge page.
- `robots` disallows all crawling.

`conftest.py` runs them on separate loopback IPs (127.0.0.1–4), because link checks treat the same host as "same site". Scans in tests pass `allow_private=True`, a `trusted_transport`, and the `FAST` config overrides (no politeness delay, no external link checks).
