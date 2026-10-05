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
| 2 | Web app shell, batch audits with live progress, settings | ⏳ visual direction to be chosen |
| 3–9 | Dashboard, AI design review, PDF, prices, CRM, archive, launch | planned |

The full brief is in [`docs/SPEC.sk.md`](docs/SPEC.sk.md); how it maps to a SaaS
is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

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
