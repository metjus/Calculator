#!/bin/bash
# Installs the Python core (core/) with its dev dependencies so tests and the
# linter work in Claude Code cloud sessions. Idempotent; synchronous.
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
"$VENV/bin/pip" install --quiet -e "$ROOT/core[dev]"

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$VENV/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
  echo "export VIRTUAL_ENV=\"$VENV\"" >> "$CLAUDE_ENV_FILE"
  # Playwright's bundled browser is not installed in cloud containers; use the preinstalled Chromium.
  if [ -x /opt/pw-browsers/chromium ]; then
    echo "export WEBAUDIT_CHROMIUM_PATH=/opt/pw-browsers/chromium" >> "$CLAUDE_ENV_FILE"
  fi
fi
