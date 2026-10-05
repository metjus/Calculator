# Web Audit SaaS – architecture

The original brief (`docs/SPEC.sk.md`) describes a local desktop program. This
repository builds the same product as a **web SaaS** from day one. Everything in
the brief stays; this document records how each desktop decision translates and
which new concerns a hosted, multi-customer product adds.

## Decisions at a glance

| Brief (desktop) | SaaS translation | Why |
|---|---|---|
| Python core package, no GUI dependency | **Kept as is** – `core/` (`webaudit`) is imported by the API workers and the CLI | The brief already demanded a UI-free core “for a future SaaS”; we start there |
| PySide6 / CustomTkinter window | **React + TypeScript (Vite) single-page app**, plain CSS on design tokens (`web/DESIGN-SYSTEM.md`), Lucide icons, charts rendered as SVG | Browser UI is the product; SPA keeps the Python side a pure API; Lucide is the icon set the brief names |
| Background thread, window always responsive | **Job queue + worker processes**; progress streamed to the browser over **Server-Sent Events** | Scans take 30–150 s per site and must survive page reloads and many concurrent users |
| SQLite | **PostgreSQL** (SQLite only for local dev and tests) | Concurrent writers, row-level tenant isolation, managed backups |
| Data folder (DB, screenshots, PDFs) movable between PCs | **Object storage** (S3-compatible) for screenshots and PDFs; **workspace export** (ZIP of JSON + files) replaces “move the folder” | No local disk in a hosted product; export keeps the “take your data with you” promise |
| Backup on start, keep last 10 | Managed Postgres point-in-time recovery + nightly logical dumps; per-workspace export on demand | Same intent (never lose data), done by the platform |
| “Open PDF folder” | “Download PDF” per audit and “Download all (ZIP)” per batch | |
| API keys stored locally, never in Git | Per-workspace keys **encrypted at rest** (envelope encryption, key in the platform secret store), shown masked, “Test key” button | Customers bring their own keys (see below); keys never reach the browser after saving |
| PyInstaller .exe | **Docker images** (api, worker, web) deployed to an EU region | GDPR, no installer support burden |
| JSON config files (weights, prices, texts) | **Defaults ship as JSON in `core/`**; each workspace stores **overrides** (JSON in Postgres) edited in Settings; core deep-merges them (`Config.load(overrides=…)`) | Same editability, per customer |

## Components

```
browser (React SPA) ──HTTPS──▶ api (FastAPI)
                                  │  REST + SSE
                                  ├──▶ PostgreSQL  (tenants, customers, audits, results, settings, job queue)
                                  ├──▶ object storage (screenshots, PDFs, logos)
                                  └──▶ job queue ──▶ worker × N (webaudit core + Playwright Chromium)
                                                        │
                                                        └──▶ egress proxy ──▶ audited websites,
                                                                              PageSpeed API, Claude API,
                                                                              Google Places, Overpass
```

- **api** – FastAPI (Python, so it imports `webaudit` directly for validation,
  config schemas and PDF rendering). Auth, workspaces, CRUD for customers,
  audits, settings; starts batch jobs; streams progress.
- **worker** – runs `webaudit.Scanner.scan_many()`; forwards `ProgressEvent`s
  to Postgres (`LISTEN/NOTIFY`) so the api can push them over SSE as
  “Web 3 of 20 – kadernictvo-x.sk: taking mobile screenshot” and the live log.
  Stop = a cancel flag the worker checks between sites (`cancel` event in core).
- **Queue** – Postgres-backed (`SELECT … FOR UPDATE SKIP LOCKED`, e.g. the
  *procrastinate* library). No Redis to operate at the start; swap later if
  volume demands.
- **web** – static SPA on a CDN.

## Multi-tenancy

- Every row carries `workspace_id`; Postgres row-level security enforces it in
  addition to application checks.
- Users belong to workspaces (a solo web designer = one workspace with one
  user; agencies can invite colleagues later).
- Plans limit audits per month and concurrent scans; the worker pool enforces
  per-workspace concurrency so one large batch can’t starve others.

## Bring your own keys

PageSpeed, Claude and Google Places keys are entered by each customer, as in
the brief. Benefits: zero variable API cost for us, no shared quota, and Google
Places terms stay between Google and the key owner. The AI design review shows
a cost estimate before a batch runs (the brief’s checkbox + estimate).

## Politeness and safety when *we* are the crawler

A desktop tool scans from one person’s IP; a SaaS scans from shared data-centre
IPs for many customers. The core already implements per-site rules (robots.txt
incl. wildcards and `Crawl-delay`, one request at a time per host, a minimum
delay, a time budget per site, capped page/link counts, an honest
`WebAuditBot` user agent with an info URL). The SaaS adds:

1. **Global per-host rate limit** across all workers and tenants – the core
   accepts an injected `RateLimiter`; production uses a Postgres-backed one.
2. **Shared robots.txt cache** (TTL 24 h) so 50 customers auditing the same
   competitor don’t hit it 50 times.
3. **Result reuse** – a site audited by anyone in the last N hours can be served
   from cache for the raw checks (scores are recomputed with each workspace’s
   weights).
4. **SSRF protection** – customers type URLs our servers fetch, and the pages
   they point to run JavaScript in our browser. The core refuses non-http(s)
   schemes, credentials in URLs and any host resolving to
   loopback/private/link-local/reserved ranges (incl. `169.254.169.254`):
   - the HTTP client checks every redirect hop (`fetch.py`);
   - **Chromium sends all traffic through an in-process guarded proxy**
     (`egress.py`) that resolves each host once, refuses non-public addresses
     and connects to exactly the address it checked. This covers what
     Playwright route handlers cannot see (redirect hops, WebSockets) and DNS
     rebinding for the browser; a regression test drives a hostile page that
     tries all of these.
   The HTTP client still resolves DNS itself, so production workers must
   additionally have **no network route to internal services** (network
   policy, or an egress proxy such as Smokescreen, plus IMDSv2 on AWS).
5. **Abuse limits** – per-workspace rate limits, max URLs per batch, and the
   “Do not contact” list blocks re-auditing without confirmation (as in the brief).

## Data protection (GDPR)

- Still no contact data: the checks record only *whether* a phone/e-mail
  exists; nothing personal is stored (asserted in tests).
- Customer notes are personal-ish data → retention rules from the brief
  (archive after X months, delete notes after X years with warning) run as
  scheduled jobs per workspace.
- Google Places: store only `place_id` permanently; names/addresses are fetched
  on demand. OpenStreetMap data is ODbL → attribution in the UI and PDFs.
- EU hosting, DPA for customers, sub-processor list (hosting, Anthropic,
  Google).

## Stage plan (the brief’s stages, adapted)

| # | Stage | SaaS notes | Status |
|---|---|---|---|
| 1 | Core: single-site scan, all non-AI checks, score, CLI | `core/` | **done** |
| 2 | Batch scan + UI: visual direction, CSV import, business search, settings & keys, progress, cookie bars, Cloudflare detection | `api/` + `web/` in direction B “Petrol” – see *Stage 2 as built* below | **done** – waiting for your feedback |
| 3 | Audit dashboard | Postgres schema, metrics, charts, table, site detail | |
| 4 | Screenshots + AI design review, competitor comparison | screenshots already captured by core; Claude review + cost estimate | |
| 5 | PDF audit (SK/CS/EN), offer page, preview, vCard QR | HTML → PDF via Playwright in the worker; texts already in `texts.json` | |
| 6 | Prices + “Check my prices” | | |
| 7 | CRM: customers, statuses, history, reminders, sales charts, no-website leads | | |
| 8 | Archive, duplicates, re-contact, retention | scheduled jobs | |
| 9 | Polish, real-site testing, deployment | Docker, CI, EU hosting instead of PyInstaller | |

## Stage 2 as built

What exists now, and where it deliberately differs from the target picture above:

- **api** (`api/src/webaudit_api`): FastAPI with opaque session cookies
  (`wa_session`, httpOnly, SameSite=Lax, argon2 passwords) and a CSRF header
  (`X-Requested-With: webaudit`) required on every mutating `/api` call. Each
  user owns one workspace; every query filters by `workspace_id`.
- **Keys**: PageSpeed, Claude and Google Places keys are Fernet-encrypted with a
  key derived from `WEBAUDIT_SECRET_KEY`, returned only as `last4`, and testable
  (`POST /api/settings/keys/{service}/test`). Envelope encryption via a KMS is a
  stage 9 task.
- **Queue and worker**: audits and their sites are rows; `AuditWorker` claims the
  oldest queued audit (`FOR UPDATE SKIP LOCKED` on Postgres), runs
  `Scanner.scan_many()` and writes every `ProgressEvent` as an `audit_events` row.
  It runs inside the API process by default (`WEBAUDIT_INPROCESS_WORKER`) or
  separately as `webaudit-worker`. Running audits are re-queued on restart.
- **Progress**: `GET /api/audits/{id}/events` is an SSE stream that polls
  `audit_events` (resumes with `Last-Event-ID`). Works on SQLite and Postgres;
  `LISTEN/NOTIFY` is a later optimisation. Stop sets `cancel_requested`; sites in
  progress finish, the rest become `cancelled`.
- **Storage**: screenshots live under `WEBAUDIT_DATA_DIR`, served only through an
  authorised endpoint that confines paths to that folder. Object storage comes
  with deployment (stage 9).
- **Business search** (`/api/search/*`): areas from Photon (OSM), businesses from
  Google Places Text Search (New, field mask without phone numbers) and Overpass,
  merged by domain, then by name + distance. Only `place_id` is stored for Google
  results, OSM names may be stored (ODbL attribution in the UI). Every search
  shows a cost estimate first; usage is counted per workspace and month.
  Templates save the area + category.
- **Customers** (`/api/companies`): every audited or searched business, with
  “no website” leads; the CRM in stage 7 adds statuses, notes and reminders.
- **web**: React 19 + Vite, routes `/`, `/search`, `/audits`, `/audits/new`,
  `/audits/:id`, `/customers`, `/settings`, `/login`, `/signup`. Self-hosted
  IBM Plex Sans (no Google Fonts request, GDPR). Light and dark themes.

Configuration is environment-only (`WEBAUDIT_*`, see `api/README.md`); nothing
secret is read from files in the repository.

## Desktop first, SaaS later (decided after stage 2)

While only the owner uses the tool, it ships as a Windows program
(`desktop/`, WebAudit.exe) so there is no server to pay for. It is the same
code: the launcher starts the FastAPI app in **local mode** on 127.0.0.1 and
shows the React UI in a native window (Edge WebView2). Local mode means one
local user signed in with a per-launch token, no sign-up, a loopback-only Host
check against DNS rebinding, and a Quit button. Data lives in `data/` next to
the exe, as the original brief asked (one movable folder, backup on every
start, newest 10 kept). Scans use the Edge built into Windows. The SaaS path
(Docker image, server settings) stays in the repository and is picked up again
when the tool is sold to other designers.

## Claude Code export (added after stage 2, on request)

After a scan, each scored website can be downloaded as a ZIP for Claude Code
(per site, or per audit with an index): `CLAUDE.md` with working rules,
`REPORT.md` with every problem ranked by impact including **where** it is
(CSS selectors, URLs, files), how to fix it and how to verify the fix,
`PAGE.md` describing what the homepage contains, the server and rendered HTML,
screenshots and `scan.json`. The designer unzips it into the website's project
and works through the fixes with Claude Code.

Privacy: page text is kept only with e-mail addresses and phone numbers
replaced (`core/src/webaudit/redact.py`); the HTML snapshots live next to the
screenshots and share their retention. Person names in page text are not
detected. Page text is untrusted input for Claude Code, and the export says so
in `CLAUDE.md`.

## Repository layout

```
core/      Python package `webaudit` – scanning, checks, scoring, texts (stage 1)
docs/      brief (SPEC.sk.md), this document
api/       FastAPI service `webaudit_api` – auth, workspaces, audits, worker, search (stage 2)
web/       React SPA in direction B “Petrol” (stage 2); FastAPI serves web/dist in production
```
