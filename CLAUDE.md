# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A website-audit SaaS for web designers (brief in Slovak: `docs/SPEC.sk.md`; SaaS translation and stage plan: `docs/ARCHITECTURE.md`). The brief is built **in stages, showing the user each result before continuing**; check the stage table in `docs/ARCHITECTURE.md` before starting new work. The brief also requires showing UI design proposals before writing any UI code.

Stages 1–2 are built: `core/` (scanning library + CLI), `api/` (FastAPI service `webaudit_api`) and `web/` (React SPA in direction B “Petrol”, tokens and components in `web/DESIGN-SYSTEM.md`).

## Commands (run from `core/`)

```bash
python -m venv ../.venv && ../.venv/bin/pip install -e ".[dev]"   # dev deps incl. playwright, trustme
../.venv/bin/pytest                                   # all tests (~5 s)
../.venv/bin/pytest tests/test_units.py -k robots     # a subset
../.venv/bin/pytest tests/test_scan.py::test_static_scan_modern_vs_legacy
../.venv/bin/webaudit scan example.sk --lang sk       # CLI; --no-browser, --csv, --json, --screenshots DIR
../.venv/bin/ruff check src tests && ../.venv/bin/ruff format --check src tests   # lint + format (config in pyproject)
```

API and web:

```bash
cd api && ../.venv/bin/pytest                          # API tests (~4 s), reuse core fixture sites
../.venv/bin/ruff check src tests && ../.venv/bin/ruff format --check src tests
cd web && npm run build                                # tsc --noEmit + vite build → web/dist (served by the API)
WEBAUDIT_SECRET_KEY=dev ../.venv/bin/webaudit-api      # :8000; `npm run dev` in web/ proxies /api to it
```

Cloud sessions run `.claude/hooks/session-start.sh`, which creates `/home/user/Calculator/.venv` (repo-root `.venv`), installs `core[dev]` and `api[dev]`, runs `npm install` in `web/` and exports `WEBAUDIT_CHROMIUM_PATH`.

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
4. **Keep**: `inventory.build` describes what the homepage contains; with a files folder the scanner also saves redacted, gzip'd HTML snapshots next to the screenshots. `claude_export.py` turns a result into the Claude Code folder/ZIP (`webaudit scan --claude-export`, `GET /api/audits/{id}[/sites/{sid}]/claude-export`).

Invariants that span files:

- **A check id must be listed in four places:** its `@check(...)` decorator, `defaults/scoring.json` (area + weight; unlisted checks are informational), `defaults/texts.json` (SK/CS/EN `label/problem/impact/solution`, optional `warn` override) and `defaults/devnotes.json` (English `fix/verify/effort` for the Claude Code export). `tests/test_units.py` and `tests/test_export.py` assert the texts and notes exist.
- **Evidence says where the problem is.** Put CSS selectors (`dom.css_path`, `cssPath` in browser.py), URLs or file names in `CheckResult.evidence`; `REPORT.md` in the Claude Code export lists them under “Where”.
- **SSRF boundary:** user URLs go through `NetGuard.check_url` on every httpx hop; Chromium is launched with `egress.GuardedProxy` as its proxy (the route handler is only a fast-fail — Playwright doesn't route redirect hops or WebSockets). Never launch a browser or HTTP client that bypasses these. `test_browser_cannot_reach_internal_hosts` must keep passing.
- **Contact data is never stored.** Trust checks record only booleans/counts; evidence lists must not contain phone numbers or e-mails. Any page text that is kept (the `inventory`, page snapshots, title values) goes through `redact.redact_text` / `redact_html` first. The e2e and export tests assert this.
- **Thresholds and weights live in `defaults/*.json`, not in code.** Read them through `ctx.t(name)` (scanner thresholds) and `ctx.signatures` (CMS/library/tracker/firewall patterns). Users override them with a config dir and the SaaS with per-workspace dicts, both deep-merged by `Config.load`.
- **Sites without a score have a `SiteState` and reason.** The states are `unreachable`, `protected`, `disallowed`, `invalid` and `cancelled`. These sites are excluded from statistics.
- **Progress for the UI** flows through `ProgressEvent` (`on_event` callback): `step` events, log events with levels ok/warn/error, and a final `done` event carrying the `ScanResult`.
- **UI language is English;** client-facing text (texts.json, future PDFs) is SK/CS/EN, in formal address, hedged wording, with no invented numbers.

## API and web (`api/src/webaudit_api`, `web/src`)

- Every query is scoped by `user.workspace_id`; endpoints that take an id load the row and compare its workspace (404 otherwise).
- Mutating `/api` requests need the header `X-Requested-With: webaudit` (CSRF guard in `main.py`); `web/src/lib/api.ts` adds it.
- API keys are only stored encrypted (`security.KeyBox`) and returned as `last4`. Never log or return a decrypted key.
- The worker (`worker.py`) is the only place scans run; it maps core `ProgressEvent`s to `audit_events` rows that the SSE endpoint streams.
- Google Places results: store only `place_id`. OSM names may be stored; show the ODbL attribution wherever OSM data appears.
- External services in tests: `app.state.search_transport` (httpx `MockTransport`); never call real Google/OSM from tests.
- UI code uses the token roles in `web/src/styles/tokens.css` and components in `web/src/components/ui.tsx`; no raw hex in components (Leaflet shapes are the documented exception).

## Tests

`tests/sites.py` defines the fixture websites:
- `modern` is served over HTTPS with a trustme CA.
- `legacy` is a 2010-style site.
- `cloudflare` returns a challenge page.
- `robots` disallows all crawling.
- `attacker` + `internal` exercise the SSRF boundary: the attacker page tries to reach `internal` through redirects, a WebSocket and fetch. `FixtureServers.hits` records what each site received.

`conftest.py` runs them on separate loopback IPs (127.0.0.1–6), because link checks treat the same host as "same site". Scans in tests pass `allow_private=True`, a `trusted_transport`, and the `FAST` config overrides (no politeness delay, no external link checks).
