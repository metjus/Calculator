"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .db import create_schema, make_engine, make_sessionmaker
from .deps import current_user
from .models import User
from .routers import audits, auth, companies, search, settings
from .security import CSRF_HEADER, CSRF_VALUE, KeyBox
from .settings import Settings
from .worker import AuditWorker

log = logging.getLogger("webaudit.api")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def create_app(
    app_settings: Settings | None = None,
    *,
    start_worker: bool | None = None,
    worker_kwargs: dict | None = None,
    on_quit: Callable[[], None] | None = None,
) -> FastAPI:
    """``on_quit`` is called by ``POST /api/local/quit`` in the desktop app (local mode)."""
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
        # Desktop app: only answer requests addressed to the loopback name, so a web page using
        # DNS rebinding (evil.example → 127.0.0.1) cannot read the local API.
        if app_settings.local_mode:
            host = request.headers.get("host", "").rsplit(":", 1)[0].strip("[]").lower()
            if host not in LOCAL_HOSTS:
                return JSONResponse({"detail": "Invalid host"}, status_code=400)
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
    app.include_router(companies.router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/local/quit", status_code=204, include_in_schema=False)
    async def quit_app(user: User = Depends(current_user)) -> Response:
        if not app_settings.local_mode or on_quit is None:
            raise HTTPException(404, "Not Found")
        asyncio.get_running_loop().call_later(0.3, on_quit)  # let the response reach the window first
        return Response(status_code=204)

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
