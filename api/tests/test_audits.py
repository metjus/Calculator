from __future__ import annotations

import asyncio
import dataclasses
import io
import ssl
import zipfile

import httpx
import pytest
from conftest import signup
from sqlalchemy import select

from webaudit_api.models import AuditSite, Company
from webaudit_api.worker import AuditWorker

FAST = {
    "scanner": {
        "politeness": {"min_delay_between_requests_s": 0.0},
        "limits": {"max_external_links_checked": 0},
        "timeouts": {"site_total_s": 60},
    }
}


def make_worker(app, sites) -> AuditWorker:
    ctx = ssl.create_default_context()
    sites.ca.configure_trust(ctx)
    return AuditWorker(
        app.state.sessionmaker,
        app.state.settings,
        app.state.keybox,
        poll_interval=0.2,
        use_browser=False,  # browser paths are covered by the core tests
        transport=httpx.AsyncHTTPTransport(verify=ctx),
        config_overrides=FAST,
    )


async def test_create_run_and_stream_audit(user_client: httpx.AsyncClient, app, sites) -> None:
    text = f"{sites.urls['modern']}\n{sites.urls['legacy']}, {sites.urls['cloudflare']}\nnot a url\n{sites.urls['modern']}"
    created = await user_client.post("/api/audits", json={"project": "Demo Trnava", "urls": text})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["audit"]["total"] == 3 and body["audit"]["status"] == "queued"
    assert {"not", "a", "url"} <= {i["input"] for i in body["invalid"]}
    assert body["skipped_duplicates"] == 1
    audit_id = body["audit"]["id"]

    assert await make_worker(app, sites).run_once() is True

    detail = (await user_client.get(f"/api/audits/{audit_id}")).json()
    assert detail["status"] == "done" and detail["done_count"] == 3 and detail["error_count"] == 1
    by_url = {s["input_url"]: s for s in detail["sites"]}
    modern, legacy, cloudflare = (by_url[sites.urls[n]] for n in ("modern", "legacy", "cloudflare"))
    assert modern["state"] == "ok" and modern["score"] > legacy["score"]
    assert legacy["category"] in ("critical", "weak") and legacy["top_issue"]
    assert cloudflare["state"] == "protected" and cloudflare["score"] is None

    full = (await user_client.get(f"/api/audits/{audit_id}/sites/{legacy['id']}")).json()
    assert full["result"]["score"]["total"] == legacy["score"]
    assert full["issues"][0]["label"] and full["issues"][0]["summary"] and full["issues"][0]["impact"] > 0

    # The SSE stream replays the history and ends once the audit is finished.
    stream = await user_client.get(f"/api/audits/{audit_id}/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    events = [line.split(": ", 1)[1] for line in stream.text.splitlines() if line.startswith("event: ")]
    assert events[0] == "queued" and "audit_started" in events and events.count("site_done") == 3
    assert events[-2:] == ["audit_done", "end"]
    assert "step" in events and "log" in events

    resumed = await user_client.get(f"/api/audits/{audit_id}/events", headers={"Last-Event-ID": "999999"})
    assert [line for line in resumed.text.splitlines() if line.startswith("event: ")] == ["event: end"]

    listing = (await user_client.get("/api/audits")).json()
    assert listing[0]["id"] == audit_id
    summary = (await user_client.get("/api/audits/stats/summary")).json()
    assert summary == {"audits": 1, "scored_sites": 2}


async def test_csv_with_no_website_rows(user_client: httpx.AsyncClient, app) -> None:
    csv = "url;nazov_firmy;konkurencia;projekt\nkadernictvo-x.sk;Kaderníctvo X;a.sk;Kaderníctva Trnava\n;Pekáreň bez webu;;Kaderníctva Trnava\n"
    created = await user_client.post("/api/audits/csv", files={"file": ("leads.csv", csv.encode("utf-8"), "text/csv")})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["audit"]["total"] == 1 and body["no_website_leads"] == 1
    async with app.state.sessionmaker() as db:
        companies = {c.name: c for c in await db.scalars(select(Company))}
        site = await db.scalar(select(AuditSite))
    assert companies["Pekáreň bez webu"].url is None and companies["Pekáreň bez webu"].project == "Kaderníctva Trnava"
    assert companies["Kaderníctvo X"].domain == "kadernictvo-x.sk"
    assert site.competitors == ["https://a.sk/"]

    listed = (await user_client.get("/api/companies")).json()
    assert {c["name"]: c["has_website"] for c in listed} == {"Kaderníctvo X": True, "Pekáreň bez webu": False}


async def test_only_invalid_input_is_rejected(user_client: httpx.AsyncClient) -> None:
    response = await user_client.post("/api/audits", json={"urls": "nothing here"})
    assert response.status_code == 422
    bad_csv = await user_client.post("/api/audits/csv", files={"file": ("x.csv", b"foo,bar\n1,2\n", "text/csv")})
    assert bad_csv.status_code == 422


async def test_stop_queued_audit_and_isolation(user_client: httpx.AsyncClient, make_client, sites) -> None:
    audit = (await user_client.post("/api/audits", json={"urls": sites.urls["legacy"]})).json()["audit"]
    stopped = (await user_client.post(f"/api/audits/{audit['id']}/stop")).json()
    assert stopped["status"] == "cancelled"

    async with make_client() as other:
        await signup(other, "other@example.com")
        assert (await other.get(f"/api/audits/{audit['id']}")).status_code == 404
        assert (await other.get(f"/api/audits/{audit['id']}/events")).status_code == 404
        assert (await other.get("/api/audits")).json() == []


async def test_stop_running_audit_skips_remaining_sites(user_client: httpx.AsyncClient, app, sites) -> None:
    urls = "\n".join([sites.urls["legacy"], sites.urls["modern"], sites.urls["cloudflare"]])
    audit_id = (await user_client.post("/api/audits", json={"urls": urls})).json()["audit"]["id"]
    worker = make_worker(app, sites)
    worker.settings = type(app.state.settings)(**{**app.state.settings.__dict__, "scan_concurrency": 1})
    claimed = await worker.claim()
    assert claimed == audit_id
    await user_client.post(f"/api/audits/{audit_id}/stop")  # running -> cancel requested
    await worker.process(audit_id)
    detail = (await user_client.get(f"/api/audits/{audit_id}")).json()
    assert detail["status"] == "cancelled"
    assert {s["state"] for s in detail["sites"]} == {"cancelled"}
    assert detail["done_count"] == 3 and detail["error_count"] == 0


async def test_screenshot_paths_cannot_escape_data_dir(user_client: httpx.AsyncClient, app, sites) -> None:
    audit_id = (await user_client.post("/api/audits", json={"urls": sites.urls["legacy"]})).json()["audit"]["id"]
    async with app.state.sessionmaker() as db:
        site = await db.scalar(select(AuditSite))
        site.result = {"screenshots": {"desktop": "../../../../etc/passwd"}}
        await db.commit()
        site_id = site.id
    response = await user_client.get(f"/api/audits/{audit_id}/sites/{site_id}/screenshots/desktop")
    assert response.status_code == 404


async def test_claude_code_export(user_client: httpx.AsyncClient, app, sites, make_client) -> None:
    urls = f"{sites.urls['legacy']}\n{sites.urls['cloudflare']}"
    audit_id = (await user_client.post("/api/audits", json={"project": "Autoservisy Trnava", "urls": urls})).json()["audit"]["id"]
    assert (await user_client.get(f"/api/audits/{audit_id}/claude-export")).status_code == 409  # not finished yet
    assert await make_worker(app, sites).run_once() is True
    detail = (await user_client.get(f"/api/audits/{audit_id}")).json()
    legacy, cloudflare = (next(s for s in detail["sites"] if s["input_url"] == sites.urls[n]) for n in ("legacy", "cloudflare"))

    response = await user_client.get(f"/api/audits/{audit_id}/sites/{legacy['id']}/claude-export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "webaudit-127.0.0.2-" in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    root = archive.namelist()[0].split("/")[0]
    assert {f"{root}/CLAUDE.md", f"{root}/REPORT.md", f"{root}/PAGE.md", f"{root}/page/source.html"} <= set(archive.namelist())
    for name in archive.namelist():
        text = archive.read(name).decode("utf-8")
        assert "0905" not in text and "lena-example" not in text, name  # contact data stays out
    assert "[phone]" in archive.read(f"{root}/page/source.html").decode()

    not_scored = await user_client.get(f"/api/audits/{audit_id}/sites/{cloudflare['id']}/claude-export")
    assert not_scored.status_code == 409

    batch = await user_client.get(f"/api/audits/{audit_id}/claude-export")
    assert batch.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(batch.content)).namelist()
    batch_root = names[0].split("/")[0]
    assert batch_root.startswith("webaudit-autoservisy-trnava-")
    assert f"{batch_root}/sites/127.0.0.2/REPORT.md" in names
    index = zipfile.ZipFile(io.BytesIO(batch.content)).read(f"{batch_root}/CLAUDE.md").decode()
    assert "## Not scored" in index and "Cloudflare" in index

    async with make_client() as other:
        await signup(other, "intruder@example.com")
        assert (await other.get(f"/api/audits/{audit_id}/claude-export")).status_code == 404
        assert (await other.get(f"/api/audits/{audit_id}/sites/{legacy['id']}/claude-export")).status_code == 404


@pytest.mark.parametrize("path", ["/api/audits", "/api/settings", "/api/search/options"])
async def test_endpoints_require_login(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401


async def test_an_interrupted_audit_is_stopped_and_does_not_block_the_next_one(user_client: httpx.AsyncClient, app, sites) -> None:
    """Closing the window mid-audit used to re-run that audit ahead of everything new."""
    urls = "\n".join([sites.urls["legacy"], sites.urls["modern"]])
    old_id = (await user_client.post("/api/audits", json={"urls": urls})).json()["audit"]["id"]
    worker = make_worker(app, sites)
    assert await worker.claim() == old_id  # claimed, then the program is closed
    async with app.state.sessionmaker() as db:
        site = await db.scalar(select(AuditSite).where(AuditSite.audit_id == old_id, AuditSite.position == 1))
        site.state, site.step = "running", "loading homepage"
        await db.commit()

    new_id = (await user_client.post("/api/audits", json={"urls": sites.urls["cloudflare"]})).json()["audit"]["id"]
    await worker.recover()  # next start of the program

    old = (await user_client.get(f"/api/audits/{old_id}")).json()
    assert old["status"] == "cancelled" and old["done_count"] == 2
    assert {s["state"] for s in old["sites"]} == {"cancelled"}
    assert "program was closed" in old["sites"][0]["state_reason"]
    events = (await user_client.get(f"/api/audits/{old_id}/events")).text
    assert "closed before this audit finished" in events and "Audit stopped" in events

    assert await worker.claim() == new_id  # the new audit is next, not the interrupted one


async def test_a_queued_audit_says_what_it_waits_for(user_client: httpx.AsyncClient, app, sites) -> None:
    first = (await user_client.post("/api/audits", json={"urls": sites.urls["legacy"]})).json()["audit"]["id"]
    second = (await user_client.post("/api/audits", json={"urls": sites.urls["modern"]})).json()["audit"]["id"]
    worker = make_worker(app, sites)
    assert await worker.claim() == first

    queue = (await user_client.get(f"/api/audits/{second}")).json()["queue"]
    assert queue == {"ahead": 0, "running_audit_id": first, "worker": "unknown", "worker_error": None}

    app.state.worker = worker
    worker.last_error = "OperationalError: database is locked"
    assert (await user_client.get(f"/api/audits/{second}")).json()["queue"]["worker"] == "stopped"
    worker.polling = True
    assert (await user_client.get(f"/api/audits/{second}")).json()["queue"]["worker"] == "running"
    del app.state.worker

    await worker.process(first)
    assert (await user_client.get(f"/api/audits/{first}")).json()["queue"] is None  # not queued any more


async def test_the_worker_loop_starts_again_after_a_failure(app, sites) -> None:
    worker = make_worker(app, sites)
    worker.restart_delay = 0.01
    stop = asyncio.Event()
    calls = 0

    async def flaky(_stop: asyncio.Event) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        stop.set()

    worker._loop = flaky  # noqa: SLF001 - the supervisor is what is under test
    await asyncio.wait_for(worker.run(stop), 5)
    assert calls == 2 and worker.state == "stopped" and worker.last_error == "RuntimeError: boom"


async def test_desktop_mode_closes_audits_left_in_the_queue(user_client: httpx.AsyncClient, app, sites) -> None:
    """One worker, one user: a leftover queued audit would hold up the next one invisibly."""
    stale = (await user_client.post("/api/audits", json={"urls": sites.urls["legacy"]})).json()["audit"]["id"]
    worker = make_worker(app, sites)
    worker.settings = dataclasses.replace(worker.settings, local_mode=True)
    await worker.recover()  # the program starts again

    detail = (await user_client.get(f"/api/audits/{stale}")).json()
    assert detail["status"] == "cancelled" and detail["sites"][0]["state"] == "cancelled"
    assert await worker.claim() is None

    fresh = (await user_client.post("/api/audits", json={"urls": sites.urls["modern"]})).json()["audit"]["id"]
    assert await worker.claim() == fresh  # audits started from now on run normally
