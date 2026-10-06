"""Where the program and its data live, single-instance lock and database backups."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

APP_NAME = "WebAudit"
BACKUPS_KEPT = 10


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder of WebAudit.exe; the current folder when run from source."""
    return Path(sys.executable).resolve().parent if frozen() else Path.cwd()


def bundle_dir() -> Path:
    """Read-only files shipped with the program (the built web app)."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return Path(__file__).resolve().parents[3]  # repository root


def web_dist() -> Path:
    return bundle_dir() / "web" if frozen() else bundle_dir() / "web" / "dist"


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("ok", "utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir(override: str | None = None) -> Path:
    """``data`` next to the exe; if that folder is read-only (e.g. Program Files), the user's app data."""
    if override:
        return Path(override).resolve()
    beside = app_dir() / "data"
    if _writable(beside):
        return beside
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return base / APP_NAME / "data"


def unblock_downloaded(folder: Path) -> int:
    """Remove the “downloaded from the internet” mark from the program's DLLs; returns how many.

    Windows Explorer marks every file unzipped from a downloaded ZIP (a ``Zone.Identifier``
    stream). .NET then refuses to load Python.Runtime.dll, and the program window (WebView2
    through pythonnet) fails with “Failed to resolve Python.Runtime.Loader.Initialize”.
    """
    if sys.platform != "win32":
        return 0
    removed = 0
    for path in folder.rglob("*.dll"):
        try:
            os.remove(f"{path}:Zone.Identifier")  # NTFS alternate data stream
            removed += 1
        except OSError:
            pass  # not marked, or not allowed to change it
    return removed


class InstanceLock:
    """Keeps a second copy of the program from opening the same data folder."""

    def __init__(self, folder: Path) -> None:
        self.path = folder / ".lock"
        self.info_path = folder / "instance.json"
        self._handle: TextIO | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")  # noqa: SIM115 - held open for the life of the program
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def publish(self, **info: Any) -> None:
        """Tell a second launch where the running copy listens, so it can open another window."""
        self.info_path.write_text(json.dumps(info), "utf-8")

    def running_instance(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.info_path.read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self.info_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._handle.close()
        self._handle = None


def backup_database(database: Path, folder: Path, keep: int = BACKUPS_KEPT, now: datetime | None = None) -> Path | None:
    """Copy the database before the program opens it; keep the newest ``keep`` copies."""
    if not database.is_file():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"webaudit-{(now or datetime.now()):%Y%m%d-%H%M%S}.db"
    source = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)  # file:///C:/… on Windows
    try:
        copy = sqlite3.connect(target)
        try:
            source.backup(copy)  # consistent copy even with a WAL journal
        finally:
            copy.close()
    finally:
        source.close()
    for old in sorted(folder.glob("webaudit-*.db"))[:-keep]:
        old.unlink(missing_ok=True)
    return target
