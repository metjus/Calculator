# Web Audit desktop (WebAudit.exe)

The same app as the SaaS (`core/` + `api/` + `web/`), run locally:

- `app.py` starts the API and its audit worker with uvicorn on a free port on
  127.0.0.1 in a background thread, then opens a native window (pywebview →
  Edge WebView2 on Windows) at `/api/auth/local?token=…`. The API runs in
  **local mode**: one local user, signed in with a per-launch token instead of a
  password; requests must be addressed to `127.0.0.1`/`localhost` (DNS-rebinding
  guard); “Quit Web Audit” in the sidebar replaces “Sign out”.
- `files.py` puts all data in `data/` next to the exe (or `%LOCALAPPDATA%\WebAudit\data`
  if that folder is read-only), keeps a second copy from opening the same data
  (`data/.lock`; a second launch just opens another window), and backs up the
  database on every start (newest 10 in `data/backups`).
- Scanning uses the installed Microsoft Edge (`WEBAUDIT_BROWSER_CHANNEL=msedge`),
  falling back to Playwright's own Chromium.

## Build

```bash
cd web && npm ci && npm run build && cd ..
pip install -e "core[browser]" -e api -e "desktop[dev]"
pyinstaller desktop/WebAudit.spec --noconfirm      # → dist/WebAudit/WebAudit.exe (+ _internal/)
```

Windows builds run in `.github/workflows/desktop-windows.yml`, which also runs the
test suites on Windows with Edge and self-tests the exe on a real website.

## Run and test without a window

```bash
python -m webaudit_desktop --no-window              # prints the sign-in URL
python -m webaudit_desktop --self-test https://example.com --data /tmp/wa-data
pytest desktop/tests
```

`--self-test` drives the real API (sign-in, audit, screenshots, Claude Code
export) and writes `selftest.json`; the log is in `data/logs/webaudit.log`.
