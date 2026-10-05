# Web Audit – one image with the web app, the API, the audit worker and Chromium.
#
#   docker compose up --build        → http://localhost:8000
#
# Data (SQLite database, screenshots, page snapshots, the generated secret key)
# lives in the /data volume. See README.md → "Run it" for production settings.

# ---------------------------------------------------------------- web app (React)
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ------------------------------------------------------------ API + worker + core
# Microsoft's Playwright image ships Chromium and its system libraries, so the
# build needs no apt or browser downloads. Keep the tag and the pinned
# playwright version below in step.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

WORKDIR /app
COPY core/pyproject.toml core/README.md core/
COPY core/src core/src
COPY api/pyproject.toml api/
COPY api/src api/src
RUN pip install "playwright==1.63.0" "./core[browser]" ./api

COPY --from=web /web/dist /app/web/dist

RUN mkdir -p /data && chown pwuser:pwuser /data

ENV WEBAUDIT_HOST=0.0.0.0 \
    WEBAUDIT_PORT=8000 \
    WEBAUDIT_DATA_DIR=/data \
    WEBAUDIT_DATABASE_URL=sqlite+aiosqlite:////data/webaudit.db \
    WEBAUDIT_WEB_DIST=/app/web/dist

USER pwuser
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["webaudit-api"]
