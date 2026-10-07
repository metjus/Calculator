"""Stage 7: the CRM — statuses, the timeline, contacts, follow-ups, the charts and deleting.

The rule the brief repeats: no contact person, phone number or e-mail is ever stored.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from test_audits import make_worker

from webaudit_api.crm import STATUSES
from webaudit_api.models import Company, CompanyEvent


async def add(client: httpx.AsyncClient, **body) -> dict:
    created = await client.post("/api/companies", json=body)
    assert created.status_code == 201, created.text
    return created.json()


async def test_a_customer_moves_through_the_funnel_and_the_card_remembers_it(user_client: httpx.AsyncClient) -> None:
    card = await add(user_client, name="Kaderníctvo Lena", url="lena.sk", project="Salóny")
    customer = card["customer"]
    assert customer["status"] == "audited" and customer["has_website"] is True and customer["domain"] == "lena.sk"
    cid = customer["id"]

    logged = (await user_client.post(f"/api/companies/{cid}/contacts", json={"way": "phone", "note": "Zavolal som, ozve sa."})).json()
    assert logged["customer"]["status"] == "contacted"  # the first contact moves the customer on
    assert logged["customer"]["contacts"] == 1 and logged["customer"]["last_contact"]

    for step, extra in (("waiting", {}), ("interested", {}), ("proposal", {}), ("deal", {"deal_value": 540})):
        card = (await user_client.post(f"/api/companies/{cid}/status", json={"status": step, **extra})).json()
    assert card["customer"]["status"] == "deal" and card["customer"]["deal_value"] == 540

    kinds = [entry["kind"] for entry in card["timeline"]]
    assert kinds.count("status") == 6 and kinds.count("contact") == 1  # audited + contacted + four steps
    assert card["timeline"][0]["status"] == "deal"  # newest first
    phone = next(entry for entry in card["timeline"] if entry["kind"] == "contact")
    assert phone["way"] == "phone" and "Zavolal" in phone["note"]


async def test_the_follow_up_list_is_who_needs_a_nudge(user_client: httpx.AsyncClient, app) -> None:
    quiet = (await add(user_client, name="Ticho", url="ticho.sk"))["customer"]["id"]
    due = (await add(user_client, name="Termín", url="termin.sk"))["customer"]["id"]
    fresh = (await add(user_client, name="Čerstvé", url="cerstve.sk"))["customer"]["id"]
    await user_client.post(f"/api/companies/{quiet}/status", json={"status": "waiting"})
    await user_client.post(f"/api/companies/{fresh}/status", json={"status": "waiting"})
    await user_client.patch(
        f"/api/companies/{due}", json={"next_step": "Poslať návrh", "next_step_at": (datetime.now(UTC) - timedelta(days=1)).isoformat()}
    )
    # "Waiting" since nine days ago is overdue; since today is not.
    async with app.state.sessionmaker() as db:
        company = await db.get(Company, quiet)
        company.status_at = datetime.now(UTC) - timedelta(days=9)
        await db.commit()

    body = (await user_client.get("/api/companies")).json()
    reasons = {row["name"]: row["reason"] for row in body["follow_ups"]}
    assert reasons == {"Ticho": "waiting", "Termín": "next_step"}
    assert body["total"] == 3 and len(body["rows"]) == 3

    # A customer marked "do not contact" never shows up there.
    await user_client.patch(f"/api/companies/{quiet}", json={"do_not_contact": True})
    assert [row["name"] for row in (await user_client.get("/api/companies")).json()["follow_ups"]] == ["Termín"]


async def test_filters_and_the_charts_describe_what_is_shown(user_client: httpx.AsyncClient) -> None:
    salon = (await add(user_client, name="Salón", url="salon.sk", project="Salóny"))["customer"]["id"]
    await add(user_client, name="Kaviareň", url="kava.sk", project="Kaviarne")
    lead = (await add(user_client, name="Bez webu"))["customer"]
    assert lead["status"] == "lead" and lead["has_website"] is False

    await user_client.post(f"/api/companies/{salon}/status", json={"status": "contacted"})
    await user_client.post(f"/api/companies/{salon}/status", json={"status": "deal", "deal_value": 900})

    body = (await user_client.get("/api/companies", params={"project": "Salóny"})).json()
    assert [row["name"] for row in body["rows"]] == ["Salón"]
    assert body["projects"] == ["Kaviarne", "Salóny"] and body["total"] == 3

    only_leads = (await user_client.get("/api/companies", params={"website": "no"})).json()
    assert [row["name"] for row in only_leads["rows"]] == ["Bez webu"]
    assert (await user_client.get("/api/companies", params={"q": "kava"})).json()["rows"][0]["name"] == "Kaviareň"
    assert [r["name"] for r in (await user_client.get("/api/companies", params={"status": "deal"})).json()["rows"]] == ["Salón"]

    stats = (await user_client.get("/api/companies")).json()["stats"]
    assert stats["total"] == 3 and stats["deal_value"] == 900
    assert stats["conversion"] == {"contacted": 1, "interested": 1, "deals": 1, "interested_pct": 100, "deal_pct": 100}
    assert {row["status"]: row["count"] for row in stats["funnel"]}["deal"] == 1
    assert stats["weeks"] and stats["weeks"][-1]["deals"] == 1
    assert stats["answer_days"] is not None  # contacted → deal happened in this test


async def test_a_lead_that_gets_a_website_can_be_audited(user_client: httpx.AsyncClient) -> None:
    lead = (await add(user_client, name="Nový klient"))["customer"]["id"]
    card = (await user_client.patch(f"/api/companies/{lead}", json={"url": "novyklient.sk"})).json()
    assert card["customer"]["status"] == "audited" and card["customer"]["has_website"] is True
    assert [e["status"] for e in card["timeline"] if e["kind"] == "status"][0] == "audited"


async def test_the_proposal_warns_after_thirty_days(user_client: httpx.AsyncClient, app) -> None:
    cid = (await add(user_client, name="Návrh", url="navrh.sk"))["customer"]["id"]
    card = (await user_client.patch(f"/api/companies/{cid}", json={"proposal_url": "https://ukazka.sk/lena"})).json()
    assert card["customer"]["proposal_sent_at"] and card["customer"]["proposal_warning"] is False
    assert any(entry["kind"] == "proposal" for entry in card["timeline"])

    async with app.state.sessionmaker() as db:
        company = await db.get(Company, cid)
        company.proposal_sent_at = datetime.now(UTC) - timedelta(days=31)
        await db.commit()
    assert (await user_client.get(f"/api/companies/{cid}")).json()["customer"]["proposal_warning"] is True


async def test_notes_and_the_customer_can_be_deleted(user_client: httpx.AsyncClient, app) -> None:
    cid = (await add(user_client, name="Zmazať", url="zmazat.sk", notes="Súkromná poznámka"))["customer"]["id"]
    await user_client.post(f"/api/companies/{cid}/contacts", json={"way": "email", "note": "Poslal som ponuku"})

    cleared = (await user_client.delete(f"/api/companies/{cid}/notes")).json()
    assert cleared["customer"]["notes"] is None
    assert all(entry["note"] is None for entry in cleared["timeline"])  # the written words go, the dates stay
    assert any(entry["kind"] == "contact" for entry in cleared["timeline"])

    removed = await user_client.delete(f"/api/companies/{cid}", params={"keep_url": "true"})
    assert removed.status_code == 200 and removed.json()["kept_url"] == "yes"
    async with app.state.sessionmaker() as db:
        left = list(await db.scalars(select(Company)))
        assert len(left) == 1 and left[0].do_not_contact is True and left[0].name is None and left[0].url == "https://zmazat.sk/"
        assert (await db.scalars(select(CompanyEvent))).all() == []


async def test_duplicates_are_pointed_out(user_client: httpx.AsyncClient) -> None:
    first = (await add(user_client, name="Dvojník", url="dvojnik.sk"))["customer"]["id"]
    second = (await add(user_client, name="Dvojník", url="dvojnik2.sk"))["customer"]["id"]
    found = (await user_client.get(f"/api/companies/{second}/duplicates")).json()
    assert [row["id"] for row in found] == [first] and found[0]["status_label"] == STATUSES["audited"]["label"]


async def test_a_scanned_website_appears_on_the_timeline(user_client: httpx.AsyncClient, app, sites) -> None:
    created = (await user_client.post("/api/audits", json={"urls": sites.urls["legacy"]})).json()
    await make_worker(app, sites).run_once()
    site = (await user_client.get(f"/api/audits/{created['audit']['id']}")).json()["sites"][0]
    rows = (await user_client.get("/api/companies")).json()["rows"]
    assert len(rows) == 1 and rows[0]["score"] == site["score"] and rows[0]["site_id"] == site["id"]

    card = (await user_client.get(f"/api/companies/{rows[0]['id']}")).json()
    audit_entry = next(entry for entry in card["timeline"] if entry["kind"] == "audit")
    assert audit_entry["score"] == site["score"] and audit_entry["audit_id"] == created["audit"]["id"]


async def test_customers_are_scoped_to_their_workspace(user_client: httpx.AsyncClient, make_client) -> None:
    from conftest import signup

    cid = (await add(user_client, name="Môj", url="moj.sk"))["customer"]["id"]
    async with make_client() as other:
        await signup(other, "other@example.com")
        assert (await other.get("/api/companies")).json()["rows"] == []
        assert (await other.get(f"/api/companies/{cid}")).status_code == 404
        assert (await other.post(f"/api/companies/{cid}/status", json={"status": "deal"})).status_code == 404
        assert (await other.delete(f"/api/companies/{cid}")).status_code == 404
