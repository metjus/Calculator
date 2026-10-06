# webaudit-api

FastAPI service for the Web Audit SaaS: accounts and workspaces, API keys,
batch audits with a background worker and live progress (SSE), business search
and the customer list. It imports the scanning core (`../core`, package
`webaudit`) directly.

## Run locally

```bash
# from the repository root
python -m venv .venv
.venv/bin/pip install -e "core[dev]" -e "api[dev]"
.venv/bin/webaudit-api                     # http://127.0.0.1:8000, API docs at /api/docs

# the web app, in a second terminal (proxies /api to :8000)
cd web && npm install && npm run dev       # http://127.0.0.1:5173
```

For production, build the SPA once (`cd web && npm run build`); the API then
serves `web/dist` itself (override with `WEBAUDIT_WEB_DIST`). The repository's
`Dockerfile` / `docker-compose.yml` do all of this in one image (see the root README).

## Configuration (environment only)

| Variable | Default | Meaning |
|---|---|---|
| `WEBAUDIT_SECRET_KEY` | generated once into `<data dir>/secret.key` | Encrypts stored API keys. On a server set it explicitly and keep a copy; never commit it. Losing it makes stored API keys unreadable. |
| `WEBAUDIT_DATABASE_URL` | `sqlite+aiosqlite:///./webaudit.db` | Use `postgresql+asyncpg://…` in production |
| `WEBAUDIT_DATA_DIR` | `./data` | Screenshots, page snapshots and the generated `secret.key` |
| `WEBAUDIT_INPROCESS_WORKER` | `true` | Run the audit worker inside the API; set `false` and start `webaudit-worker` separately |
| `WEBAUDIT_SCAN_CONCURRENCY` | `2` | Websites scanned at the same time per audit |
| `WEBAUDIT_MAX_URLS_PER_AUDIT` | `200` | |
| `WEBAUDIT_SIGNUP_ENABLED` | `true` | |
| `WEBAUDIT_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `WEBAUDIT_ALLOW_PRIVATE_TARGETS` | `false` | Disables the SSRF guard. **Local testing only.** |
| `WEBAUDIT_PHOTON_URL` | public Photon | Area autocomplete |
| `WEBAUDIT_OVERPASS_URL` | three public Overpass servers | OSM business search; comma-separated, tried in order until one answers |
| `WEBAUDIT_MAP_TILE_URL` | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | Upstream for map preview tiles. The browser loads them from `/api/search/tiles/…`, which fetches each tile once with the app's User-Agent and caches it in `<data>/tiles` (OSM blocks direct use without one). Use your own tile provider for production traffic |
| `WEBAUDIT_MAP_ATTRIBUTION` | OpenStreetMap contributors | Attribution shown on the map; change it with the tile provider |
| `WEBAUDIT_HOST`, `WEBAUDIT_PORT` | `127.0.0.1`, `8000` | |
| `WEBAUDIT_CHROMIUM_PATH` | Playwright's browser | Chromium for screenshots and browser checks |

API keys for PageSpeed, Claude and Google Places are entered per workspace in
**Settings**, stored encrypted and never returned in full.

## Tests

```bash
cd api && ../.venv/bin/pytest          # uses the fixture websites from core/tests
../.venv/bin/ruff check src tests && ../.venv/bin/ruff format --check src tests
```

External services (Google, Overpass, Photon) are replaced with `httpx.MockTransport`
in tests; scans run against local fixture sites.
