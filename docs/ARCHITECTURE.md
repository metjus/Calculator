# Web Audit SaaS – architecture

The original brief (`docs/SPEC.sk.md`) describes a local desktop program. This
repository builds the same product as a **web SaaS** from day one. Everything in
the brief stays; this document records how each desktop decision translates and
which new concerns a hosted, multi-customer product adds.

## Decisions at a glance

| Brief (desktop) | SaaS translation | Why |
|---|---|---|
| Python core package, no GUI dependency | **Kept as is** – `core/` (`webaudit`) is imported by the API workers and the CLI | The brief already demanded a UI-free core “for a future SaaS”; we start there |
| PySide6 / CustomTkinter window | **React + TypeScript (Vite) single-page app**, Tailwind CSS, Lucide icons, charts rendered as SVG | Browser UI is the product; SPA keeps the Python side a pure API; Lucide is the icon set the brief names |
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
4. **SSRF protection** – customers type URLs our servers fetch. The core refuses
   non-http(s) schemes, credentials in URLs and any host resolving to
   loopback/private/link-local/reserved ranges (incl. `169.254.169.254`), on
   every redirect hop and for every request the headless browser makes.
   Because DNS rebinding can defeat in-process checks, **workers egress only
   through a proxy that enforces the same rule** (e.g. Smokescreen) and have no
   route to internal services.
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
| 2 | Batch scan + UI: visual direction, CSV import, business search, settings & keys, progress, cookie bars, Cloudflare detection | FastAPI skeleton, auth, workspace, job queue, SSE progress, SPA shell in the chosen direction. Cookie bars + Cloudflare detection already in core | direction mockups published – **waiting for your choice** |
| 3 | Audit dashboard | Postgres schema, metrics, charts, table, site detail | |
| 4 | Screenshots + AI design review, competitor comparison | screenshots already captured by core; Claude review + cost estimate | |
| 5 | PDF audit (SK/CS/EN), offer page, preview, vCard QR | HTML → PDF via Playwright in the worker; texts already in `texts.json` | |
| 6 | Prices + “Check my prices” | | |
| 7 | CRM: customers, statuses, history, reminders, sales charts, no-website leads | | |
| 8 | Archive, duplicates, re-contact, retention | scheduled jobs | |
| 9 | Polish, real-site testing, deployment | Docker, CI, EU hosting instead of PyInstaller | |

## Repository layout

```
core/      Python package `webaudit` – scanning, checks, scoring, texts (stage 1)
docs/      brief (SPEC.sk.md), this document
api/       FastAPI service            (stage 2)
web/       React SPA                  (stage 2, after the visual direction is chosen)
```
