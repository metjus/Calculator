"""Stage 4: the AI design review option, its cost estimate, a review on demand, and competitor scans.

The Claude API is never called: the worker and the API get a fake reviewer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from test_audits import make_worker
from test_dashboard import add_audit, add_company, scan
from webaudit.ai_review import AIReviewError

from webaudit_api.models import Audit, AuditSite, CompetitorScan

REVIEW = {
    "score": 52,
    "verdict": "Web pôsobí zastarano.",
    "strengths": ["Jasné logo"],
    "weaknesses": ["Hlavička: menu je malé", "Mobil: text je drobný"],
    "looks_dated": True,
    "language": "sk",
    "model": "claude-opus-5-5",
    "input_tokens": 2800,
    "output_tokens": 1200,
}


async def save_claude_key(client: httpx.AsyncClient) -> None:
    assert (await client.put("/api/settings/keys/claude", json={"key": "sk-ant-test-1234"})).status_code == 200


async def test_estimate_and_the_option_needs_a_key(user_client: httpx.AsyncClient, app) -> None:
    estimate = (await user_client.get("/api/audits/ai-estimate", params={"sites": 10})).json()
    assert estimate["configured"] is False and estimate["model"] == "claude-opus-5-5"
    low, high = estimate["per_site_usd"]["low"], estimate["per_site_usd"]["high"]
    assert 0 < low < high < 0.2 and abs(estimate["total_usd"]["high"] - high * 10) < 0.1

    refused = await user_client.post("/api/audits", json={"urls": "https://a.sk", "ai_review": True})
    assert refused.status_code == 422 and "Claude API key" in refused.text

    await save_claude_key(user_client)
    assert (await user_client.get("/api/audits/ai-estimate")).json()["configured"] is True
    created = await user_client.post("/api/audits", json={"urls": "https://a.sk", "ai_review": True})
    async with app.state.sessionmaker() as db:
        audit = await db.get(Audit, created.json()["audit"]["id"])
        assert audit.options == {"ai_review": True}


async def test_worker_hands_the_key_to_the_reviewer(user_client: httpx.AsyncClient, app, sites) -> None:
    await save_claude_key(user_client)
    keys = []

    def factory(key: str):
        keys.append(key)

        async def reviewer(*_args):  # without the browser there are no screenshots to send
            raise AssertionError("not called without screenshots")

        return reviewer

    created = (await user_client.post("/api/audits", json={"urls": sites.urls["modern"], "ai_review": True})).json()
    worker = make_worker(app, sites)
    worker.ai_reviewer_factory = factory
    await worker.run_once()
    assert keys == ["sk-ant-test-1234"]
    site = (await user_client.get(f"/api/audits/{created['audit']['id']}")).json()["sites"][0]
    detail = (await user_client.get(f"/api/audits/{created['audit']['id']}/sites/{site['id']}")).json()
    assert detail["ai_review"]["status"] == "na" and "no desktop screenshot" in detail["ai_review"]["summary"]


async def test_competitors_are_scanned_once_and_compared(user_client: httpx.AsyncClient, app, sites) -> None:
    text = f"{sites.urls['modern']}\n{sites.urls['legacy']}"
    created = await user_client.post(
        "/api/audits", json={"project": "Salóny", "urls": text, "competitors": f"{sites.urls['cloudflare']} not-a-url"}
    )
    body = created.json()
    assert any(i["error"].startswith("competitor:") for i in body["invalid"])
    audit_id = body["audit"]["id"]
    await make_worker(app, sites).run_once()

    async with app.state.sessionmaker() as db:
        scans = list(await db.scalars(select(CompetitorScan).where(CompetitorScan.audit_id == audit_id)))
    assert [(c.url, c.state) for c in scans] == [(sites.urls["cloudflare"], "protected")]  # once, though two sites list it

    detail = (await user_client.get(f"/api/audits/{audit_id}")).json()
    modern = next(s for s in detail["sites"] if s["input_url"] == sites.urls["modern"])
    view = (await user_client.get(f"/api/audits/{audit_id}/sites/{modern['id']}")).json()
    assert view["comparison"]["source"] == "competitors"
    (row,) = view["comparison"]["rows"]
    assert row["state"] == "protected" and row["score"] is None and row["domain"] == "127.0.0.3"
    assert view["comparison"]["self"]["https"] is True and "basics" in view["comparison"]["self"]["areas"]
    assert (await user_client.get(f"/api/audits/{audit_id}/competitors/{row['id']}/screenshots/desktop")).status_code == 404
    events = (await user_client.get(f"/api/audits/{audit_id}/events")).text
    assert "Comparing with 1 competitor website" in events

    # Without listed competitors the detail compares with the best other websites of the audit.
    plain = (await user_client.post("/api/audits", json={"urls": text})).json()["audit"]["id"]
    await make_worker(app, sites).run_once()
    legacy = next(s for s in (await user_client.get(f"/api/audits/{plain}")).json()["sites"] if s["input_url"] == sites.urls["legacy"])
    peers = (await user_client.get(f"/api/audits/{plain}/sites/{legacy['id']}")).json()["comparison"]
    assert peers["source"] == "audit" and [r["domain"] for r in peers["rows"]] == ["127.0.0.1"]


async def test_review_on_demand_rescores_the_website(user_client: httpx.AsyncClient, app, settings) -> None:
    ws = (await user_client.get("/api/auth/me")).json()["workspace_id"]
    lena = await add_company(app, ws, "Kaderníctvo Lena", "https://lena.sk/")
    result = scan(70, "ok", issues=("trust.clickable_phone",))
    shots = settings.data_dir / "audits" / "x"
    shots.mkdir(parents=True)
    (shots / "lena-desktop.jpg").write_bytes(b"\xff\xd8desktop")
    (shots / "lena-mobile.jpg").write_bytes(b"\xff\xd8mobile")
    result["screenshots"] = {"desktop": "audits/x/lena-desktop.jpg", "mobile": "audits/x/lena-mobile.jpg"}
    result["score"]["areas"] = [{"area": "basics", "score": 100, "weight": 16, "checks": 2}]
    result.update(input_url="https://lena.sk/", final_url="https://lena.sk/", state="ok")
    audit = await add_audit(app, ws, "Salóny", [(lena, "https://lena.sk/", "ok", 70, result, datetime.now(UTC))])
    site_id = audit.sites[0].id
    url = f"/api/audits/{audit.id}/sites/{site_id}/ai-review"

    assert (await user_client.post(url)).status_code == 400  # no Claude key yet
    await save_claude_key(user_client)
    calls = []

    def factory(key: str):
        async def reviewer(desktop: bytes, mobile: bytes | None, site_url: str, language: str) -> dict:
            calls.append((key, desktop, mobile, site_url, language))
            return REVIEW

        return reviewer

    app.state.ai_reviewer_factory = factory
    view = (await user_client.post(url)).json()
    assert calls == [("sk-ant-test-1234", b"\xff\xd8desktop", b"\xff\xd8mobile", "https://lena.sk/", "sk")]
    review = view["ai_review"]
    assert review["status"] == "warn" and review["score"] == 52 and review["weaknesses"][0].startswith("Hlavička")
    assert review["cost_usd"] == round(2800 * 4 / 1e6 + 1200 * 20 / 1e6, 4)
    areas = {a["area"]: a["score"] for a in view["areas"]}
    assert areas["design_ai"] == 52
    assert view["site"]["score"] != 70  # recomputed with the design area
    async with app.state.sessionmaker() as db:
        stored = await db.get(AuditSite, site_id)
        assert stored.score == view["site"]["score"] and Path(stored.result["screenshots"]["desktop"]).name == "lena-desktop.jpg"

    def failing(_key: str):
        async def reviewer(*_args) -> dict:
            raise AIReviewError("Claude declined to review this website")

        return reviewer

    app.state.ai_reviewer_factory = failing
    failed = await user_client.post(url)
    assert failed.status_code == 502 and "declined" in failed.text
