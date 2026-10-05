"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .db import create_schema, make_engine, make_sessionmaker
from .routers import audits, auth, search, settings
from .security import CSRF_HEADER, CSRF_VALUE, KeyBox
from .settings import Settings
from .worker import AuditWorker

log = logging.getLogger("webaudit.api")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_app(app_settings: Settings | None = None, *, start_worker: bool | None = None, worker_kwargs: dict | None = None) -> FastAPI:
    app_settings = app_settings or Settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(app_settings.database_url)
        await create_schema(engine)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.settings = app_settings
        app.state.keybox = KeyBox(app_settings.secret_key)
        app_settings.data_dir.mkdir(parents=True, exist_ok=True)
        stop = asyncio.Event()
        task = None
        if app_settings.inprocess_worker if start_worker is None else start_worker:
            worker = AuditWorker(app.state.sessionmaker, app_settings, app.state.keybox, **(worker_kwargs or {}))
            app.state.worker = worker
            task = asyncio.create_task(worker.run(stop))
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(task, 30)
            await engine.dispose()

    app = FastAPI(
        title="Web Audit API", version="0.2.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json"
    )

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):  # noqa: ANN001, ANN202
        # Cookies are SameSite=Lax; state-changing API calls must also carry a custom header,
        # which a cross-site form or image cannot send.
        if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS:
            if request.headers.get(CSRF_HEADER, "").lower() != CSRF_VALUE:
                return JSONResponse({"detail": "Missing X-Requested-With header"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    app.include_router(auth.router)
    app.include_router(settings.router)
    app.include_router(audits.router)
    app.include_router(search.router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_web(app)
    return app


def _mount_web(app: FastAPI) -> None:
    """Serve the built SPA (web/dist) when present, with index.html as the fallback route."""
    dist = Path(os.environ.get("WEBAUDIT_WEB_DIST", Path(__file__).resolve().parents[3] / "web" / "dist"))
    index = dist / "index.html"
    if not index.is_file():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def run() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "webaudit_api.main:create_app",
        factory=True,
        host=os.environ.get("WEBAUDIT_HOST", "127.0.0.1"),
        port=int(os.environ.get("WEBAUDIT_PORT", "8000")),
    )
