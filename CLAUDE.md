# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A website-audit SaaS for web designers (brief in Slovak: `docs/SPEC.sk.md`; SaaS translation and stage plan: `docs/ARCHITECTURE.md`). The brief is built **in stages, showing the user each result before continuing**; check the stage table in `docs/ARCHITECTURE.md` before starting new work. The brief also requires showing UI design proposals before writing any UI code.

Stages 1–5, 7 and 8 are built (stage 6 was dropped at the owner's request): `core/` (scanning library + CLI), `api/` (FastAPI service `webaudit_api`) and `web/` (React SPA in direction B “Petrol”, tokens and components in `web/DESIGN-SYSTEM.md`). The owner uses it as a Windows program for now: `desktop/` (`webaudit_desktop`) packages the same app as WebAudit.exe (local mode, data next to the exe, scans with Edge); the SaaS deployment comes later. See `desktop/README.md`.

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
docker compose up --build                              # whole app in one image (Dockerfile at the repo root)
cd desktop && ../.venv/bin/pytest                      # launcher tests incl. a windowless self-test
../.venv/bin/pyinstaller desktop/WebAudit.spec --noconfirm   # from the repo root; needs web/dist
```

The Windows exe is built and tested by `.github/workflows/desktop-windows.yml` (core + API tests with Edge, PyInstaller, `WebAudit.exe --self-test https://example.com`).

The Docker image is based on `mcr.microsoft.com/playwright/python` (Chromium included); its tag and the `playwright==` pin in the Dockerfile must match. In cloud containers the Debian and Playwright CDNs are blocked, so test image builds with that base and `docker build --network host` plus the agent-proxy CA (see `/root/.ccr/README.md`).

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
4. **Review (optional)**: with a Claude key, `ai_review.ClaudeReviewer` sends the two screenshots to
   `claude-opus-5-5` and stores a redacted 0–100 design review; `checks/design_ai.py` grades it and
   `CheckResult.credit` carries the score into the area. Injected as `Scanner(ai_reviewer=...)`, so
   tests never call the API.
5. **Keep**: `inventory.build` describes what the homepage contains; with a files folder the scanner also saves redacted, gzip'd HTML snapshots next to the screenshots. `claude_export.py` turns a result into the Claude Code folder/ZIP (`webaudit scan --claude-export`, `GET /api/audits/{id}[/sites/{sid}]/claude-export`).

Invariants that span files:

- **A check id must be listed in four places:** its `@check(...)` decorator, `defaults/scoring.json` (area + weight; unlisted checks are informational), `defaults/texts.json` (SK/CS/EN `label/problem/impact/solution`, optional `warn` override) and `defaults/devnotes.json` (English `fix/verify/effort` for the Claude Code export). `tests/test_units.py` and `tests/test_export.py` assert the texts and notes exist.
- **Evidence says where the problem is.** Put CSS selectors (`dom.css_path`, `cssPath` in browser.py), URLs or file names in `CheckResult.evidence`; `REPORT.md` in the Claude Code export lists them under “Where”.
- **SSRF boundary:** user URLs go through `NetGuard.check_url` on every httpx hop; Chromium is launched with `egress.GuardedProxy` as its proxy (the route handler is only a fast-fail — Playwright doesn't route redirect hops or WebSockets). Never launch a browser or HTTP client that bypasses these. `test_browser_cannot_reach_internal_hosts` must keep passing.
- **The AI review costs the user money.** It runs only when the audit asked for it and a Claude key
  exists, never for competitor scans, and every screen that can start one shows the estimated price
  first (`api/ai_pricing.json`). When the API refuses a request, the reason it gives is carried into
  the message (`ai_review.api_detail`); the optional `fallbacks` parameter is dropped and retried once
  rather than costing the user the review. Its texts go through `redact_text`; screenshot text is page content,
  never instructions.
- **The same review can be done by hand in claude.ai** (a subscription is not an API key), in two places. After a scan:
  `ai_review.paste_prompt` + `POST …/sites/{id}/ai-review/import` for one website, from our two screenshots. Before one:
  `paste_prompt_many` on the new-audit screen (`POST /api/audits/ai-review/prompt`), where Claude opens the sites itself - so it sees
  animations, scrolling and menus a still frame cannot show, and the prompt uses `SYSTEM_LIVE` instead of `SYSTEM` to say so. Those
  reviews travel in `Audit.options["pasted_reviews"]` keyed by domain and the worker applies each one in `_apply_pasted_review` when its
  website has been scanned, because the score cannot exist before then. Every route ends in the same `apply_review`, so a pasted review
  lands exactly where an API one does, with no cost to show. The CSV columns and the prompts must stay in step - tests assert they do.
- **The client PDF carries nothing external.** `pdf.build_html` inlines fonts, screenshots, the logo and the QR code as `data:` URIs and
  `pdf.render` aborts every network request, so an export reaches no host and works offline; `test_nothing_in_the_report_comes_from_the_network`
  must keep passing. Its wording lives in `defaults/texts.json` under `pdf` (SK/CS/EN). Prices are typed by hand in the preview and never
  itemised in the PDF - there is no per-problem price list by design. How much of each finding the client sees is `PdfContent.detail` (`pdf.DETAIL_LEVELS`): `full` prints the three parts the brief asks for,
  `no_fix` (the default) drops the solution line, `short` explains the worst three and names the rest. It is a choice per export, kept on
  `workspaces.pdf_detail`; the report never hides *that* a problem exists, only how to repair it. Which of the three options is recommended comes from
  `pdf.recommended_option` and the `offer` block in `scoring.json` (a bad total score or a poor AI design score means a new website),
  not from a fixed column. The preview screen draws the same HTML in a sandboxed iframe
  (`POST …/pdf-html`), so it redraws in milliseconds; only the export launches Chromium. It never *navigates* to a `blob:`
  URL - the desktop shell opens external links in Windows, which has no app for one. The QR code is an inline SVG with a
  `viewBox` and the standard four-module quiet zone; without the `viewBox` a CSS size crops the symbol instead of scaling it. At 36 mm it
  scans off paper, but the preview shrinks the page to the column, which puts the code at ~75 px - unreadable by design, so
  `GET /api/settings/vcard-qr` shows the same code in Settings at a size a phone can read off the screen (measured: it decodes from ~160 px).
- **What we measure is the page we were asked to measure.** The browser closes the cookie bar before measuring, so the
  consent click must never navigate: buttons inside links are skipped, frames that only look like consent dialogs
  (`youtube-nocookie`, reCAPTCHA) are left alone, and after the click `browser.same_page` compares the URL - if the page
  moved, the scanner goes back before taking any metric or screenshot. A bar that cannot be closed is hidden with CSS.
- **Contact data is never stored.** Trust checks record only booleans/counts; evidence lists must not contain phone numbers or e-mails. Any page text that is kept (the `inventory`, page snapshots, title values) goes through `redact.redact_text` / `redact_html` first. The e2e and export tests assert this.
- **Thresholds and weights live in `defaults/*.json`, not in code.** Read them through `ctx.t(name)` (scanner thresholds) and `ctx.signatures` (CMS/library/tracker/firewall patterns). Users override them with a config dir and the SaaS with per-workspace dicts, both deep-merged by `Config.load`.
- **Sites without a score have a `SiteState` and reason.** The states are `unreachable`, `protected`, `disallowed`, `invalid` and `cancelled`. These sites are excluded from statistics.
- **Progress for the UI** flows through `ProgressEvent` (`on_event` callback): `step` events, log events with levels ok/warn/error, and a final `done` event carrying the `ScanResult`.
- **UI language is English;** client-facing text (texts.json, future PDFs) is SK/CS/EN, in formal address, hedged wording, with no invented numbers.

## API and web (`api/src/webaudit_api`, `web/src`)

- Every query is scoped by `user.workspace_id`; endpoints that take an id load the row and compare its workspace (404 otherwise).
- Schema changes: `db.create_schema` adds missing **nullable** columns to existing tables on start (the desktop database survives updates); anything else needs a real migration.
- Mutating `/api` requests need the header `X-Requested-With: webaudit` (CSRF guard in `main.py`); `web/src/lib/api.ts` adds it.
- API keys are only stored encrypted (`security.KeyBox`) and returned as `last4`. Never log or return a decrypted key.
  The services are listed in `keys.SERVICES`; a service that is dropped goes into `db.RETIRED_KEY_SERVICES`, which deletes its stored keys on start.
- Competitor websites (`competitor_scans`) are compared with, not audited: no customer, no lead, no AI
  review, excluded from every statistic.
- **The CRM** (`crm.py`, `routers/companies.py`): the status lives on `companies` and every change is also a `company_events` row, so the
  timeline needs no second source of truth. A logged contact keeps the date, the way and a note - never who was spoken to. Audits are merged
  into the timeline at read time from `audit_sites`. `GET /api/companies` answers the list, the follow-ups and the charts in one response.
- The worker (`worker.py`) is the only place scans run; it maps core `ProgressEvent`s to `audit_events` rows that the SSE endpoint streams.
  One audit runs at a time: its loop restarts itself after any failure, an audit interrupted by a restart is closed (never re-queued, which
  used to block every later audit), and `GET /api/audits/{id}` carries a `queue` field so the UI says what a waiting audit waits for.
- **The archive** (`archive.py`, stage 8): the pass runs on `GET /api/companies`, not on a scheduler. It only ever *moves* customers
  (`companies.archived_at`); a customer brought back by hand (`unarchived_at`) is left alone until their status changes again. Notes due
  for clearing are reported, never cleared without the user pressing the button. The five rules live in `workspaces.crm_rules` and are
  edited in Settings; `Rules.of(workspace)` supplies the defaults.
- A business marked `do_not_contact` is never audited unless the request carries `allow_do_not_contact`; `create_audit` returns it in
  `blocked` so the screen can ask.
- Google Places results: store only `place_id`. OSM names may be stored; show the ODbL attribution wherever OSM data appears.
- External services in tests: `app.state.search_transport` (httpx `MockTransport`); never call real Google/OSM from tests.
- **Local mode** (`WEBAUDIT_LOCAL_MODE`, desktop only): `/api/auth/local?token=` signs in the single local user with the launcher's per-launch token; the CSRF middleware also rejects any Host other than `127.0.0.1`/`localhost`; `POST /api/local/quit` calls the launcher's `on_quit`. Never enable it on a server.
- **The data folder** is the launcher's, not the API's: it passes a `local.LocalFolder` (path, pending, reveal, choose) and `GET/PUT /api/local/data-folder` plus `POST …/open` only pass requests to it. Choosing a folder never moves data - the program is running out of that database; it writes `data-location.txt` beside the exe and the next start reads it (`--data` still wins). Both are 404 on a server.
- UI code uses the token roles in `web/src/styles/tokens.css` and components in `web/src/components/ui.tsx`; no raw hex in components (Leaflet shapes are the documented exception).

## Tests

`tests/sites.py` defines the fixture websites:
- `modern` is served over HTTPS with a trustme CA.
- `legacy` is a 2010-style site.
- `cloudflare` returns a challenge page.
- `robots` disallows all crawling.
- `attacker` + `internal` exercise the SSRF boundary: the attacker page tries to reach `internal` through redirects, a WebSocket and fetch. `FixtureServers.hits` records what each site received.

`conftest.py` runs them on separate loopback IPs (127.0.0.1–6), because link checks treat the same host as "same site". Scans in tests pass `allow_private=True`, a `trusted_transport`, and the `FAST` config overrides (no politeness delay, no external link checks).
