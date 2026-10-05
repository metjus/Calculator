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

## Run the web app

```bash
python -m venv .venv && .venv/bin/pip install -e "core[dev]" -e "api[dev]"
export WEBAUDIT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
(cd web && npm install && npm run build)
.venv/bin/webaudit-api            # open http://127.0.0.1:8000 and create an account
```

API keys (PageSpeed, Claude, Google Places) are entered in **Settings** and
stored encrypted per workspace – never in a file. See
[`api/README.md`](api/README.md) for configuration and
[`web/DESIGN-SYSTEM.md`](web/DESIGN-SYSTEM.md) for the UI tokens and components.

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
