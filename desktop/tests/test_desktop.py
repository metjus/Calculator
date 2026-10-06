"""Desktop launcher: data folder, single instance, backups and a full windowless run."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from webaudit_desktop import app, files

CORE_TESTS = Path(__file__).resolve().parents[2] / "core" / "tests"


@pytest.fixture(autouse=True)
def _restore_environment():
    # configure_environment() writes os.environ directly, as the exe does at start.
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def test_data_folder_falls_back_when_program_folder_is_read_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(files, "app_dir", lambda: tmp_path / "program")
    assert files.data_dir() == tmp_path / "program" / "data"

    monkeypatch.setattr(files, "_writable", lambda folder: False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    assert files.data_dir() == tmp_path / "appdata" / "WebAudit" / "data"
    assert files.data_dir(str(tmp_path / "chosen")) == tmp_path / "chosen"


def test_second_copy_cannot_take_the_lock(tmp_path) -> None:
    first, second = files.InstanceLock(tmp_path), files.InstanceLock(tmp_path)
    assert first.acquire()
    first.publish(port=1234, token="t", pid=1)
    if sys.platform != "win32":  # flock is per open file description, so a second handle in-process conflicts too
        assert not second.acquire()
    assert second.running_instance() == {"port": 1234, "token": "t", "pid": 1}
    first.release()
    assert not (tmp_path / "instance.json").exists()
    assert second.acquire()
    second.release()


def test_backups_keep_the_newest_ten(tmp_path) -> None:
    database = tmp_path / "webaudit.db"
    with sqlite3.connect(database) as db:
        db.execute("create table t (x)")
        db.execute("insert into t values (42)")
    start = datetime(2026, 1, 1, 8, 0, 0)
    for i in range(12):
        files.backup_database(database, tmp_path / "backups", now=start + timedelta(minutes=i))
    kept = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert len(kept) == 10 and kept[0] == "webaudit-20260101-080200.db"
    with sqlite3.connect(tmp_path / "backups" / kept[-1]) as copy:
        assert copy.execute("select x from t").fetchone() == (42,)
    assert files.backup_database(tmp_path / "missing.db", tmp_path / "backups") is None


def test_build_label_names_the_commit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app, "app_dir", lambda: tmp_path)
    assert app.build_label() == app.__version__
    (tmp_path / "build.txt").write_text("e78468b\n", "utf-8")
    assert app.build_label() == f"{app.__version__} · e78468b"


def test_environment_points_the_api_at_the_data_folder(tmp_path, monkeypatch) -> None:
    for key in ("WEBAUDIT_LOCAL_MODE", "WEBAUDIT_LOCAL_TOKEN", "WEBAUDIT_DATA_DIR", "WEBAUDIT_DATABASE_URL", "WEBAUDIT_SIGNUP_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    app.configure_environment(tmp_path, "secret-token")
    from webaudit_api.settings import Settings

    settings = Settings()
    assert settings.local_mode and settings.local_token == "secret-token" and not settings.signup_enabled
    assert settings.data_dir == tmp_path
    assert settings.database_url.endswith(f"{tmp_path.as_posix()}/webaudit.db")


@pytest.fixture
def legacy_site():
    spec = importlib.util.spec_from_file_location("core_test_fixtures", CORE_TESTS / "conftest.py")
    sys.path.insert(0, str(CORE_TESTS))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    servers = module.FixtureServers()
    servers.start("legacy", "127.0.0.2")
    yield servers.urls["legacy"]
    servers.stop()


def test_windowless_self_test_audits_a_site(tmp_path, monkeypatch, legacy_site) -> None:
    """The same path WebAudit.exe --self-test takes on the Windows build machine."""
    monkeypatch.setenv("WEBAUDIT_ALLOW_PRIVATE_TARGETS", "1")  # the fixture site is on 127.0.0.2
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    if sys.platform != "win32":  # Windows scans with the installed Edge (WEBAUDIT_BROWSER_CHANNEL=msedge)
        chromium = os.environ.get("WEBAUDIT_CHROMIUM_PATH") or "/opt/pw-browsers/chromium"
        if not Path(chromium).exists():
            pytest.skip("no Chromium for the browser checks")
        monkeypatch.setenv("WEBAUDIT_CHROMIUM_PATH", chromium)
    report = tmp_path / "report.json"
    code = app.main(["--data", str(tmp_path / "data"), "--self-test", legacy_site, "--report", str(report)])
    result = json.loads(report.read_text())
    assert code == 0, json.dumps(result, indent=2)
    assert result["checks"]["browser_screenshots"]["ok"] and result["issues"]
    data = tmp_path / "data"
    assert (data / "webaudit.db").is_file() and (data / "secret.key").is_file() and (data / "logs" / "webaudit.log").is_file()
    assert not (data / "instance.json").exists()  # released on exit

    # The next start backs the database up first.
    app.main(["--data", str(data), "--self-test", legacy_site, "--report", str(report)])
    assert len(list((data / "backups").glob("webaudit-*.db"))) == 1


def test_a_new_build_replaces_an_older_running_copy(tmp_path, monkeypatch) -> None:
    """After an update, starting the new exe stops the old one instead of opening its window."""
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    import threading

    data = tmp_path / "data"
    old_lock = files.InstanceLock(data)
    assert old_lock.acquire()
    app.configure_environment(data, "old-token")
    stopped = threading.Event()

    def quit_old() -> None:
        old_lock.release()
        stopped.set()

    old = app.LocalServer(app.free_port(), quit_old)
    old.start()
    old_lock.publish(port=old.port, token="old-token", pid=1)  # an older build: no version recorded
    try:
        new_lock = files.InstanceLock(data)
        if sys.platform != "win32":
            assert not new_lock.acquire()
        assert app._replace_other_version(new_lock, timeout=20)
        assert stopped.is_set()
        new_lock.publish(port=1, token="t", pid=2, version=app.build_label())
        assert not app._replace_other_version(files.InstanceLock(data), timeout=1)  # same build: leave it running
        new_lock.release()
    finally:
        old.stop()


def test_unblock_removes_the_downloaded_mark(tmp_path) -> None:
    dll = tmp_path / "pythonnet" / "Python.Runtime.dll"
    dll.parent.mkdir()
    dll.write_bytes(b"MZ")
    if sys.platform != "win32":
        assert files.unblock_downloaded(tmp_path) == 0
        return
    Path(f"{dll}:Zone.Identifier").write_text("[ZoneTransfer]\nZoneId=3\n")  # what Explorer adds when unzipping
    assert files.unblock_downloaded(tmp_path) == 1
    assert not Path(f"{dll}:Zone.Identifier").exists() and dll.read_bytes() == b"MZ"
