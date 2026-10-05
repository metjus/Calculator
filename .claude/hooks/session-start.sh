#!/bin/bash
# Installs the Python core (core/) and API (api/) with dev dependencies and the
# web app's npm packages so tests, linters and the build work in Claude Code
# cloud sessions. Idempotent; synchronous.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
VENV="$ROOT/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -e "$ROOT/core[dev]" -e "$ROOT/api[dev]"
if command -v npm >/dev/null 2>&1 && [ -f "$ROOT/web/package-lock.json" ]; then
  (cd "$ROOT/web" && npm ci --no-audit --no-fund --loglevel=error)
fi

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$VENV/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
  echo "export VIRTUAL_ENV=\"$VENV\"" >> "$CLAUDE_ENV_FILE"
  # Playwright's bundled browser is not installed in cloud containers; use the preinstalled Chromium.
  if [ -x /opt/pw-browsers/chromium ]; then
    echo "export WEBAUDIT_CHROMIUM_PATH=/opt/pw-browsers/chromium" >> "$CLAUDE_ENV_FILE"
  fi
fi
