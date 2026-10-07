"""Stage 3: dashboard statistics, the “Check manually” decisions and the website detail view."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from webaudit_api.db import create_schema
from webaudit_api.models import Audit, AuditSite, Company

NOW = datetime.now(UTC)


def scan(
    score: int, category: str, *, https: bool = True, mobile: bool = True, cms: str | None = None, issues: tuple[str, ...] = ()
) -> dict:
    """A stored ScanResult in the shape the worker saves, reduced to what the views read."""
    checks = [
        {"id": "basics.https", "area": "basics", "status": "pass" if https else "fail", "value": https, "summary": "", "evidence": []},
        {"id": "basics.ssl_valid", "area": "basics", "status": "pass" if https else "na", "value": None, "summary": "", "evidence": []},
        {"id": "mobile.viewport", "area": "mobile", "status": "pass" if mobile else "fail", "value": None, "summary": "", "evidence": []},
        {"id": "speed.page_weight", "area": "speed", "status": "warn", "value": 3_100_000, "summary": "", "evidence": []},
        {
            "id": "trust.clickable_phone",
            "area": "trust",
            "status": "fail" if "trust.clickable_phone" in issues else "pass",
            "value": False,
            "summary": "Phone number is plain text",
            "evidence": ["header .contact > span.phone"],
        },
    ]
    return {
        "checks": checks,
        "score": {"total": score, "category": category, "areas": [{"area": "mobile", "score": 38, "weight": 20, "checks": 4}]},
        "issues": [
            {"check_id": check_id, "area": check_id.split(".")[0], "status": "fail", "impact": 5.0 - i} for i, check_id in enumerate(issues)
        ],
        "tech": {"cms": cms, "cms_version": "5.8" if cms else None, "libraries": []},
        "inventory": {
            "meta": {"title": "Kaderníctvo Lena", "description": None, "lang": "sk"},
            "headings": [{"level": 1, "text": "Vitajte"}, {"level": 2, "text": "Služby"}],
            "images": [{"src": "/a.jpg", "alt": None}, {"src": "/b.jpg", "alt": "Salón"}],
            "forms": [],
            "links": {"internal_count": 12, "external_count": 2},
        },
        "screenshots": {},
    }


async def add_audit(
    app, workspace_id: int, project: str, sites: list[tuple[Company | None, str, str, int | None, dict | None, datetime]]
) -> Audit:
    async with app.state.sessionmaker() as db:
        audit = Audit(workspace_id=workspace_id, project=project, status="done", total=len(sites), options={})
        for position, (company, url, state, score, result, finished) in enumerate(sites, start=1):
            audit.sites.append(
                AuditSite(
                    position=position,
                    input_url=url,
                    final_url=url,
                    company_id=company.id if company else None,
                    state=state,
                    state_reason="Probably protected by Cloudflare – check manually" if state == "protected" else None,
                    score=score,
                    category=(result or {}).get("score", {}).get("category"),
                    result=result,
                    started_at=finished - timedelta(seconds=20),
                    finished_at=finished,
                )
            )
        db.add(audit)
        await db.commit()
        return audit


async def add_company(app, workspace_id: int, name: str, url: str) -> Company:
    async with app.state.sessionmaker() as db:
        company = Company(workspace_id=workspace_id, name=name, url=url, domain=url.split("//")[1].strip("/"))
        db.add(company)
        await db.commit()
        return company


async def test_dashboard_counts_each_website_once(user_client: httpx.AsyncClient, app) -> None:
    ws = (await user_client.get("/api/auth/me")).json()["workspace_id"]
    lena = await add_company(app, ws, "Kaderníctvo Lena", "https://lena.sk/")
    viva = await add_company(app, ws, "Salón Viva", "https://viva.sk/")
    hotel = await add_company(app, ws, "Hotel Tatry", "https://hotel.sk/")
    old = NOW - timedelta(days=120)
    await add_audit(
        app, ws, "Hair salons", [(lena, "https://lena.sk/", "ok", 30, scan(30, "critical", mobile=False, issues=("mobile.viewport",)), old)]
    )
    await add_audit(
        app,
        ws,
        "Hair salons",
        [
            (
                lena,
                "https://lena.sk/",
                "ok",
                43,
                scan(43, "weak", mobile=False, cms="WordPress", issues=("mobile.viewport", "trust.clickable_phone")),
                NOW,
            ),
            (viva, "https://viva.sk/", "ok", 85, scan(85, "good", cms="Wix", issues=("trust.clickable_phone",)), NOW),
            (hotel, "https://hotel.sk/", "protected", None, None, NOW),
        ],
    )
    await add_audit(
        app,
        ws,
        "Car repair",
        [(None, "http://novak.sk/", "ok", 18, scan(18, "critical", https=False, mobile=False, issues=("basics.https",)), NOW)],
    )

    data = (await user_client.get("/api/dashboard")).json()
    assert data["projects"] == ["Car repair", "Hair salons"]
    assert data["metrics"] == {"audited": 3, "to_check": 1, "average": round((43 + 85 + 18) / 3), "critical": 1, "without_https": 1}
    assert data["categories"] == {"critical": 1, "weak": 1, "ok": 0, "good": 1}  # lena's older 30 is not counted twice
    assert data["https"] == {"yes": 2, "no": 1} and data["mobile"] == {"yes": 1, "no": 2}
    assert {c["name"]: c["count"] for c in data["cms"]} == {"WordPress": 1, "Wix": 1, "Not detected": 1}
    assert data["problems"][0] == {"check_id": "trust.clickable_phone", "label": "Phone number not tap-to-call", "count": 2}
    assert [w["domain"] for w in data["websites"]] == ["novak.sk", "lena.sk", "viva.sk"]  # worst first
    assert data["websites"][1]["top_issue"] == "Not adapted for mobile phones" and data["websites"][1]["company"] == "Kaderníctvo Lena"
    (manual,) = data["manual"]
    assert manual["domain"] == "hotel.sk" and manual["state"] == "protected" and manual["decision"] is None

    hair = (await user_client.get("/api/dashboard", params={"project": "Hair salons"})).json()
    assert [w["domain"] for w in hair["websites"]] == ["lena.sk", "viva.sk"]
    recent = (await user_client.get("/api/dashboard", params={"days": 30, "project": "Hair salons"})).json()
    assert recent["metrics"]["audited"] == 2

    # Checked by hand: the decision sticks to the customer and leaves the to-do count.
    marked = await user_client.put(f"/api/companies/{manual['company_id']}/manual-check", json={"decision": "contact"})
    assert marked.status_code == 200 and marked.json()["manual_check"] == "contact"
    after = (await user_client.get("/api/dashboard")).json()
    assert after["metrics"]["to_check"] == 0 and after["manual"][0]["decision"] == "contact"
    customers = {c["name"]: c for c in (await user_client.get("/api/companies")).json()["rows"]}
    assert customers["Hotel Tatry"]["manual_check"] == "contact"
    assert (await user_client.put(f"/api/companies/{manual['company_id']}/manual-check", json={"decision": None})).json()[
        "manual_check"
    ] is None
    assert (await user_client.put(f"/api/companies/{manual['company_id']}/manual-check", json={"decision": "maybe"})).status_code == 422


async def test_dashboard_and_decisions_are_private(user_client: httpx.AsyncClient, app, make_client) -> None:
    ws = (await user_client.get("/api/auth/me")).json()["workspace_id"]
    hotel = await add_company(app, ws, "Hotel Tatry", "https://hotel.sk/")
    await add_audit(app, ws, "Hotels", [(hotel, "https://hotel.sk/", "protected", None, None, NOW)])
    async with make_client() as other:
        await other.post(
            "/api/auth/signup", json={"email": "other@example.com", "password": "correct horse battery", "workspace_name": "Other"}
        )
        empty = (await other.get("/api/dashboard")).json()
        assert empty["metrics"]["audited"] == 0 and empty["manual"] == [] and empty["metrics"]["average"] is None
        assert (await other.put(f"/api/companies/{hotel.id}/manual-check", json={"decision": "skip"})).status_code == 404


async def test_site_detail_view(user_client: httpx.AsyncClient, app) -> None:
    ws = (await user_client.get("/api/auth/me")).json()["workspace_id"]
    lena = await add_company(app, ws, "Kaderníctvo Lena", "https://lena.sk/")
    await add_audit(app, ws, "Hair salons", [(lena, "https://lena.sk/", "ok", 39, scan(39, "critical"), NOW - timedelta(days=90))])
    audit = await add_audit(
        app,
        ws,
        "Hair salons",
        [(lena, "https://lena.sk/", "ok", 43, scan(43, "weak", mobile=False, cms="WordPress", issues=("trust.clickable_phone",)), NOW)],
    )
    site_id = audit.sites[0].id
    detail = (await user_client.get(f"/api/audits/{audit.id}/sites/{site_id}")).json()
    assert detail["audit"] == {"id": audit.id, "project": "Hair salons"}
    assert detail["company"]["name"] == "Kaderníctvo Lena"
    (problem,) = detail["problems"]
    assert problem["label"] == "Phone number not tap-to-call" and problem["where"] == ["header .contact > span.phone"]
    assert problem["solution"].startswith("Turn the number into a link") and problem["area_label"] == "Trust & content"
    areas = {a["area"]: a for a in detail["areas"]}
    assert areas["mobile"] == {"area": "mobile", "label": "Mobile", "score": 38, "weight": 20} and areas["design_ai"]["score"] is None
    facts = {f["label"]: f for f in detail["facts"]}
    assert facts["Mobile layout"] == {"label": "Mobile layout", "value": "No", "tone": "bad"}
    assert facts["Content system"]["value"] == "WordPress 5.8" and facts["Page weight"]["value"] == "3.1 MB"
    assert facts["PageSpeed"]["value"] == "Not measured (no key)"
    contents = {c["label"]: c["value"] for c in detail["contents"]}
    assert contents["Search description"] == "Missing" and contents["Images"] == "2 · 1 without a description"
    assert contents["Headings"] == "H1 × 1 · H2 × 1" and contents["Links"] == "12 internal · 2 external"
    assert [h["score"] for h in detail["history"]] == [43, 39]


async def test_older_database_gets_new_columns(tmp_path) -> None:
    """The desktop app keeps its database across updates; new nullable columns are added on start."""
    path = tmp_path / "old.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    await create_schema(engine)
    await engine.dispose()
    with create_engine(f"sqlite:///{path}").begin() as conn:  # the database as an earlier version left it
        conn.execute(text("ALTER TABLE companies DROP COLUMN manual_checked_at"))
        conn.execute(text("ALTER TABLE companies DROP COLUMN manual_check"))
        conn.execute(
            text("INSERT INTO companies (id, workspace_id, name, do_not_contact, created_at) VALUES (1, 1, 'Kept', 0, '2026-01-01')")
        )
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    await create_schema(engine)
    await engine.dispose()
    with create_engine(f"sqlite:///{path}").begin() as conn:
        assert {"manual_check", "manual_checked_at"} <= {c["name"] for c in inspect(conn).get_columns("companies")}
        assert conn.execute(text("SELECT name, manual_check FROM companies")).one() == ("Kept", None)
