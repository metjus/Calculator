"""WebAudit.exe: start the local server and show the app in its own window.

Double-click → the data folder is prepared (backup of the database, lock against
a second copy), the API with its audit worker starts on a free port on
127.0.0.1, and a native window (Edge WebView2 on Windows) opens the app,
already signed in through a one-time launch token. Closing the window, or
“Quit Web Audit” in the sidebar, stops everything.

``WebAudit.exe --self-test https://example.com`` runs the same stack without a
window, audits that website and writes a JSON report (used by the Windows build).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from . import __version__
from .files import InstanceLock, app_dir, backup_database, bundle_dir, data_dir, frozen, unblock_downloaded, web_dist

log = logging.getLogger("webaudit.desktop")
WINDOW_SIZE = (1366, 880)
MIN_WINDOW_SIZE = (1024, 680)  # the brief asks for a sensible minimum window size


# ------------------------------------------------------------------ setup


def _quiet_streams() -> None:
    # A windowed exe has no console: sys.stdout/stderr are None and any print would crash.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))  # noqa: SIM115


def _setup_logging(folder: Path) -> Path:
    logs = folder / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / "webaudit.log"
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler(sys.stderr))  # visible when started from a terminal
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise (and would log the launch token)
    return path


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_label() -> str:
    """“0.3.1 · e78468b”: the Windows build writes the commit to build.txt next to the exe."""
    try:
        commit = (app_dir() / "build.txt").read_text("utf-8").strip()[:12]
    except OSError:
        commit = ""
    return f"{__version__} · {commit}" if commit else __version__


def configure_environment(folder: Path, token: str) -> None:
    """Settings for the API (read by webaudit_api.settings.Settings) in desktop mode."""
    os.environ.update(
        {
            "WEBAUDIT_BUILD": build_label(),
            "WEBAUDIT_LOCAL_MODE": "1",
            "WEBAUDIT_LOCAL_TOKEN": token,
            "WEBAUDIT_DATA_DIR": str(folder),
            "WEBAUDIT_DATABASE_URL": f"sqlite+aiosqlite:///{(folder / 'webaudit.db').as_posix()}",
            "WEBAUDIT_WEB_DIST": str(web_dist()),
            "WEBAUDIT_SIGNUP_ENABLED": "false",
            "WEBAUDIT_INPROCESS_WORKER": "1",
        }
    )
    if sys.platform == "win32":
        # Scan with the Edge that ships with Windows instead of downloading Chromium.
        os.environ.setdefault("WEBAUDIT_BROWSER_CHANNEL", "msedge")


# ------------------------------------------------------------------ server


class LocalServer:
    """The FastAPI app and its worker, served by uvicorn in a background thread."""

    def __init__(self, port: int, on_quit: Callable[[], None]) -> None:
        import uvicorn
        from webaudit_api.main import create_app

        self.port = port
        app = create_app(on_quit=on_quit)
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, loop="asyncio", http="h11", ws="none", lifespan="on", log_config=None, access_log=False
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self._run, name="webaudit-server", daemon=True)
        self.error: BaseException | None = None

    def _run(self) -> None:
        try:
            asyncio.run(self.server.serve())
        except BaseException as exc:  # noqa: BLE001 - reported to the main thread
            self.error = exc
            log.exception("server stopped with an error")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout: float = 60) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError(f"the local server did not start: {self.error or 'timeout'}")
            time.sleep(0.05)
        log.info("server listening on %s", self.url)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=40)


# ------------------------------------------------------------------ window


def show_window(url: str, folder: Path, quit_event: threading.Event, windows: list[Any]) -> None:
    """Native window (Edge WebView2 on Windows); the default browser if that is unavailable."""
    try:
        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True  # ZIP exports
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # audited websites open in the normal browser
        window = webview.create_window(
            "Web Audit",
            url,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=MIN_WINDOW_SIZE,
            background_color="#F3F1EC",  # --page (light); avoids a white flash before the app paints
            text_select=True,
            zoomable=True,
        )
        windows.append(window)
        webview.start(private_mode=False, storage_path=str(folder / "webview"))
        log.info("window closed")
        return
    except Exception:  # noqa: BLE001 - no WebView2 or no GUI: fall back to the browser
        log.exception("could not open the program window; using the default browser")
    webbrowser.open(url)
    quit_event.wait()  # until “Quit Web Audit” in the sidebar


def _open_second_window(lock: InstanceLock, folder: Path) -> int:
    info = lock.running_instance()
    if not info:
        log.error("another copy holds %s but did not publish its address", folder)
        return 1
    log.info("Web Audit is already running; opening another window")
    show_window(f"http://127.0.0.1:{info['port']}/api/auth/local?token={info['token']}", folder, threading.Event(), [])
    return 0


def _replace_other_version(lock: InstanceLock, timeout: float = 45) -> bool:
    """A different build holds the data folder (e.g. the old one after an update): ask it to quit.

    Without this, starting the new WebAudit.exe only opened another window of the old,
    still running copy. Returns True once this copy holds the lock.
    """
    import httpx

    info = lock.running_instance()
    if not info or info.get("version") == build_label():
        return False
    log.info("stopping the running Web Audit %s to start %s", info.get("version", "(older)"), build_label())
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{info['port']}", headers={"X-Requested-With": "webaudit"}, timeout=10) as client:
            client.get("/api/auth/local", params={"token": info["token"]})
            client.post("/api/local/quit")
    except (httpx.HTTPError, KeyError) as exc:
        log.warning("could not ask the running copy to quit: %r", exc)
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lock.acquire():
            return True
        time.sleep(0.5)
    log.warning("the running copy did not stop within %s s", timeout)
    return False


# ---------------------------------------------------------------- self-test


def _probe(call: Callable[[], Any]) -> dict[str, Any]:
    try:
        response = call()
    except Exception as exc:  # noqa: BLE001 - informational only
        return {"error": f"{exc.__class__.__name__}: {exc}"}
    kind = response.headers.get("content-type", "")
    if kind.startswith("image/"):
        return {"status": response.status_code, "type": kind, "bytes": len(response.content)}
    data = response.json() if "json" in kind else response.text[:300]
    if isinstance(data, dict) and "results" in data:
        data = {"found": len(data["results"]), "warnings": data.get("warnings")}
    return {"status": response.status_code, "body": data}


def self_test(server: LocalServer, token: str, target: str, report: Path) -> int:
    """Audit one website through the real API, as the window would, and write a JSON report."""
    import httpx

    results: dict[str, Any] = {"version": __version__, "url": target, "checks": {}}

    def record(name: str, ok: bool, detail: Any = None) -> None:
        results["checks"][name] = {"ok": ok, "detail": detail}

    headers = {"X-Requested-With": "webaudit"}
    try:
        with httpx.Client(base_url=server.url, headers=headers, timeout=30) as client:
            signed_in = client.get("/api/auth/local", params={"token": token})
            record("sign_in", signed_in.status_code == 303)
            page = client.get("/")
            record("web_app", page.status_code == 200 and 'id="root"' in page.text)
            created = client.post("/api/audits", json={"project": "Self-test", "urls": target})
            audit_id = created.json()["audit"]["id"]
            deadline = time.monotonic() + 300
            detail = client.get(f"/api/audits/{audit_id}").json()
            while detail["status"] in ("queued", "running") and time.monotonic() < deadline:
                time.sleep(2)
                detail = client.get(f"/api/audits/{audit_id}").json()
            site = detail["sites"][0]
            record("audit_finished", detail["status"] == "done", detail["status"])
            record("site_scored", site["state"] == "ok", {"state": site["state"], "reason": site["state_reason"], "score": site["score"]})
            events = client.get(f"/api/audits/{audit_id}/events").text
            results["log"] = [json.loads(line[6:]).get("message") for line in events.splitlines() if line.startswith("data: ")]
            if site["state"] == "ok":
                full = client.get(f"/api/audits/{audit_id}/sites/{site['id']}").json()
                shots = sorted((full["result"] or {}).get("screenshots") or {})
                record("browser_screenshots", shots == ["desktop", "mobile"], shots)
                results["issues"] = [f"{i['label']} (−{i['impact']:.1f})" for i in full["issues"][:10]]
                export = client.get(f"/api/audits/{audit_id}/sites/{site['id']}/claude-export")
                record("claude_export", export.status_code == 200 and len(export.content) > 1000, len(export.content))
            # Public OSM services: reported, but they may be busy, so they don't fail the build.
            results["map_tile"] = _probe(lambda: client.get("/api/search/tiles/7/70/44"))
            area = {"label": "Trnava", "lat": 48.3774, "lon": 17.5872}
            body = {"country": "sk", "area": area, "radius_km": 5, "category_id": "hair_salon", "sources": ["osm"]}
            results["osm_search"] = _probe(lambda: client.post("/api/search/run", json=body, timeout=180))
    except Exception as exc:  # noqa: BLE001 - the report says what broke
        record("exception", False, f"{exc.__class__.__name__}: {exc}")
    results["ok"] = all(c["ok"] for c in results["checks"].values()) and bool(results["checks"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")
    log.info("self-test %s, report in %s", "passed" if results["ok"] else "FAILED", report)
    return 0 if results["ok"] else 1


# --------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    _quiet_streams()
    parser = argparse.ArgumentParser(prog="WebAudit", description="Web Audit desktop app")
    parser.add_argument("--data", help="use this data folder instead of 'data' next to the program")
    parser.add_argument("--port", type=int, help="local port (default: a free one)")
    parser.add_argument("--no-window", action="store_true", help="only run the server and print its address")
    parser.add_argument("--self-test", metavar="URL", help="audit URL without a window, write a JSON report and exit")
    parser.add_argument("--report", help="where --self-test writes its report (default: data/selftest.json)")
    parser.add_argument("--version", action="version", version=f"Web Audit {__version__}")
    args = parser.parse_args(argv)

    folder = data_dir(args.data)
    folder.mkdir(parents=True, exist_ok=True)
    log_path = _setup_logging(folder)
    log.info("Web Audit %s starting, data folder %s", build_label(), folder)

    if frozen():  # before any window opens, including a second one
        unblocked = unblock_downloaded(bundle_dir())
        if unblocked:
            log.info("removed the downloaded-from-internet mark from %d program files", unblocked)

    lock = InstanceLock(folder)
    if not lock.acquire() and not _replace_other_version(lock):
        return _open_second_window(lock, folder)
    try:
        try:
            backup = backup_database(folder / "webaudit.db", folder / "backups")
            if backup:
                log.info("database backed up to %s", backup)
        except Exception:  # noqa: BLE001 - a failed backup must not stop the program
            log.exception("database backup failed")

        token = secrets.token_urlsafe(32)
        configure_environment(folder, token)
        quit_event = threading.Event()
        windows: list[Any] = []

        def request_quit() -> None:
            quit_event.set()
            for window in windows:
                try:
                    window.destroy()
                except Exception:  # noqa: BLE001
                    pass

        server = LocalServer(args.port or free_port(), request_quit)
        server.start()
        lock.publish(port=server.port, token=token, pid=os.getpid(), version=build_label())
        try:
            if args.self_test:
                return self_test(server, token, args.self_test, Path(args.report) if args.report else folder / "selftest.json")
            sign_in = f"{server.url}/api/auth/local?token={token}"
            if args.no_window:
                print(f"Web Audit is running: {sign_in}\nLog: {log_path}\nPress Ctrl+C to stop.", flush=True)
                try:
                    quit_event.wait()
                except KeyboardInterrupt:
                    pass
            else:
                show_window(sign_in, folder, quit_event, windows)
            return 0
        finally:
            server.stop()
            log.info("stopped")
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
