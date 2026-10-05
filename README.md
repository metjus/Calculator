# Web Audit SaaS

A web application for web designers who win clients by auditing small-business
websites: scan a list of sites, score them 0–100, show what is wrong in plain
language (SK / CS / EN), export a persuasive PDF audit and track every
contacted business in a simple CRM.

> This repository previously held a small calculator demo; it has been replaced
> by this project.

## Status

| Stage | What | State |
|---|---|---|
| 1 | Scanning core: polite crawler, ~40 checks, scoring, CLI | ✅ `core/` |
| 2 | Web app (direction B “Petrol”), accounts, settings & API keys, batch audits with live progress, business search, customer list | ✅ `api/`, `web/` |
| 3–9 | Audit dashboard, AI design review, PDF, prices, CRM, archive, launch | planned |

The full brief is in [`docs/SPEC.sk.md`](docs/SPEC.sk.md); how it maps to a SaaS
is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Run it

### On your computer, with Docker (recommended)

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows, macOS or Linux).

```bash
git clone -b claude/intelligent-archimedes-112jt2 https://github.com/metjus/Calculator.git webaudit
cd webaudit
docker compose up --build -d      # first build takes a few minutes (downloads ~1 GB incl. Chromium)
```

Open <http://localhost:8000>, create your account, then add your API keys in
**Settings** (PageSpeed, Claude, Google Places – all optional). The app is only
reachable from your own computer.

| Task | Command |
|---|---|
| Stop | `docker compose down` (data is kept) |
| Start again | `docker compose up -d` |
| Update to the latest version | `git pull && docker compose up --build -d` |
| Back up your data | `docker compose cp webaudit:/data ./webaudit-backup` |
| See the log | `docker compose logs -f` |

Everything (database, screenshots, page snapshots, the generated encryption key)
lives in the Docker volume `webaudit-data`. Nothing secret is stored in the
project folder or in Git.

### Without Docker

Python 3.11+ and Node.js 20+:

```bash
python -m venv .venv && .venv/bin/pip install -e "core[browser]" -e api
.venv/bin/python -m playwright install chromium      # browser for the mobile/contrast/screenshot checks
(cd web && npm ci && npm run build)
.venv/bin/webaudit-api                                # open http://127.0.0.1:8000
```

On Windows use `.venv\Scripts\` instead of `.venv/bin/`. Data goes into `./data`
and `./webaudit.db` (both ignored by Git).

### On a server (for clients or a team)

The same image runs on any Docker host. Before exposing it to the internet:
put it behind HTTPS (e.g. Caddy or Traefik), set `WEBAUDIT_COOKIE_SECURE=true`,
set your own `WEBAUDIT_SECRET_KEY` and keep a copy of it, turn off sign-up with
`WEBAUDIT_SIGNUP_ENABLED=false` once your accounts exist, and use your own map
tile provider (`WEBAUDIT_MAP_TILE_URL`). The full list of settings is in
[`api/README.md`](api/README.md). Multi-server operation (PostgreSQL, separate
workers, backups) is part of stage 9.

See [`web/DESIGN-SYSTEM.md`](web/DESIGN-SYSTEM.md) for the UI tokens and components.

## Try the core

```bash
cd core
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
webaudit scan kadernictvo-x.sk --lang sk
pytest
```

See [`core/README.md`](core/README.md) for options (CSV input, JSON output,
screenshots, PageSpeed key, config overrides).
