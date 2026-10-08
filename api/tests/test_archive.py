"""Stage 8: the archive, re-contacting, duplicates and the retention of notes.

The rules the brief insists on: nobody is ever deleted automatically, and notes are never
cleared without asking - the program only says who is due.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from test_audits import make_worker
from test_crm import add

from webaudit_api.models import Company


async def age(app, company_id: int, *, status_days: int | None = None, archived_days: int | None = None) -> None:
    """Move a customer's dates into the past so a rule that counts months can be tested."""
    async with app.state.sessionmaker() as db:
        company = await db.get(Company, company_id)
        if status_days is not None:
            company.status_at = datetime.now(UTC) - timedelta(days=status_days)
        if archived_days is not None:
            company.archived_at = datetime.now(UTC) - timedelta(days=archived_days)
        await db.commit()


async def test_a_finished_customer_moves_to_the_archive_and_can_come_back(user_client: httpx.AsyncClient, app) -> None:
    old = (await add(user_client, name="Starý", url="stary.sk"))["customer"]["id"]
    fresh = (await add(user_client, name="Čerstvý", url="cerstvy.sk"))["customer"]["id"]
    for cid in (old, fresh):
        await user_client.post(f"/api/companies/{cid}/status", json={"status": "not_interested"})
    await age(app, old, status_days=120)  # four months: past the default three

    body = (await user_client.get("/api/companies")).json()
    assert [row["name"] for row in body["rows"]] == ["Čerstvý"]  # the archived one is out of the list
    assert body["archived"] == 1 and body["total"] == 1 and body["stats"]["total"] == 1

    archived = (await user_client.get("/api/companies", params={"archived": "yes"})).json()
    assert [row["name"] for row in archived["rows"]] == ["Starý"]
    assert archived["rows"][0]["archived_at"]

    card = (await user_client.get(f"/api/companies/{old}")).json()
    assert [entry["kind"] for entry in card["timeline"]][0] == "archived"

    back = (await user_client.post(f"/api/companies/{old}/unarchive")).json()
    assert back["customer"]["archived_at"] is None
    assert {row["name"] for row in (await user_client.get("/api/companies")).json()["rows"]} == {"Starý", "Čerstvý"}


async def test_an_old_rejection_is_offered_again(user_client: httpx.AsyncClient, app) -> None:
    stale = (await add(user_client, name="Dávno nie", url="davno.sk"))["customer"]["id"]
    recent = (await add(user_client, name="Nedávno nie", url="nedavno.sk"))["customer"]["id"]
    won = (await add(user_client, name="Zákazka", url="zakazka.sk"))["customer"]["id"]
    await user_client.post(f"/api/companies/{stale}/status", json={"status": "no_answer"})
    await user_client.post(f"/api/companies/{recent}/status", json={"status": "not_interested"})
    await user_client.post(f"/api/companies/{won}/status", json={"status": "deal", "deal_value": 500})
    for cid in (stale, won):
        await age(app, cid, status_days=400)  # over a year
    await age(app, recent, status_days=120)  # archived, but the rejection is still fresh

    body = (await user_client.get("/api/companies")).json()
    assert [row["name"] for row in body["recontact"]] == ["Dávno nie"]  # a deal is not a rejection

    # Someone who asked not to be contacted is never offered again.
    await user_client.patch(f"/api/companies/{stale}", json={"do_not_contact": True})
    assert (await user_client.get("/api/companies")).json()["recontact"] == []


async def test_notes_are_only_ever_cleared_after_the_owner_agrees(user_client: httpx.AsyncClient, app, sites) -> None:
    created = (await user_client.post("/api/audits", json={"urls": sites.urls["legacy"]})).json()
    await make_worker(app, sites).run_once()
    cid = (await user_client.get("/api/companies")).json()["rows"][0]["id"]
    await user_client.patch(f"/api/companies/{cid}", json={"notes": "Volal som, vraj neskôr."})
    await user_client.post(f"/api/companies/{cid}/status", json={"status": "no_answer"})
    await age(app, cid, status_days=800)

    body = (await user_client.get("/api/companies", params={"archived": "yes"})).json()
    assert body["archived"] == 1
    await age(app, cid, archived_days=800)  # over the two years the rule allows

    body = (await user_client.get("/api/companies", params={"archived": "yes"})).json()
    assert [row["id"] for row in body["notes_due"]] == [cid]
    assert (await user_client.get(f"/api/companies/{cid}")).json()["customer"]["notes"]  # nothing was deleted

    assert (await user_client.post("/api/companies/clear-due-notes")).json() == {"cleared": 1}
    card = (await user_client.get(f"/api/companies/{cid}")).json()
    assert card["customer"]["notes"] is None
    assert card["customer"]["url"] and card["customer"]["score"] is not None  # business, address and result stay
    assert [entry["kind"] for entry in card["timeline"]][0] == "notes_cleared"
    assert any(entry["kind"] == "audit" for entry in card["timeline"])
    assert (await user_client.get("/api/companies", params={"archived": "yes"})).json()["notes_due"] == []
    assert created["audit"]["id"]


async def test_adding_a_business_warns_about_the_one_already_there(user_client: httpx.AsyncClient) -> None:
    first = (await add(user_client, name="Kaviareň u Jana", url="ujana.sk"))["customer"]["id"]
    await user_client.post(f"/api/companies/{first}/status", json={"status": "contacted"})

    by_domain = (await user_client.get("/api/companies/check", params={"url": "ujana.sk"})).json()
    assert [row["id"] for row in by_domain["duplicates"]] == [first]
    assert by_domain["duplicates"][0]["status"] == "contacted" and by_domain["duplicates"][0]["status_at"]
    assert by_domain["do_not_contact"] is False

    by_name = (await user_client.get("/api/companies/check", params={"name": "kaviareň u jana"})).json()
    assert [row["id"] for row in by_name["duplicates"]] == [first]
    assert (await user_client.get("/api/companies/check", params={"name": "Niekto iný"})).json()["duplicates"] == []

    await user_client.patch(f"/api/companies/{first}", json={"do_not_contact": True})
    assert (await user_client.get("/api/companies/check", params={"url": "https://ujana.sk/"})).json()["do_not_contact"] is True


async def test_an_import_leaves_out_the_businesses_marked_do_not_contact(user_client: httpx.AsyncClient, sites) -> None:
    legacy, modern = sites.urls["legacy"], sites.urls["modern"]
    known = (await add(user_client, url=legacy, name="Už oslovený"))["customer"]["id"]
    await user_client.post(f"/api/companies/{known}/status", json={"status": "waiting"})
    blocked = (await add(user_client, url=modern, name="Nekontaktovať"))["customer"]["id"]
    await user_client.patch(f"/api/companies/{blocked}", json={"do_not_contact": True})

    created = (await user_client.post("/api/audits", json={"urls": f"{legacy} {modern}"})).json()
    assert [row["name"] for row in created["blocked"]] == ["Nekontaktovať"]
    assert [row["name"] for row in created["known"]] == ["Už oslovený"]
    assert created["audit"]["total"] == 1  # only the one that is allowed

    confirmed = (await user_client.post("/api/audits", json={"urls": modern, "allow_do_not_contact": True})).json()
    assert confirmed["blocked"] == [] and confirmed["audit"]["total"] == 1


async def test_the_owner_sets_the_rules(user_client: httpx.AsyncClient, app) -> None:
    assert (await user_client.get("/api/settings")).json()["crm_rules"]["archive_after_months"] == 3
    saved = await user_client.put(
        "/api/settings/crm-rules",
        json={"archive_after_months": 1, "recontact_after_months": 2, "clear_notes_after_years": 1, "waiting_days": 3, "proposal_days": 10},
    )
    assert saved.json()["crm_rules"] == {
        "archive_after_months": 1,
        "recontact_after_months": 2,
        "clear_notes_after_years": 1,
        "waiting_days": 3,
        "proposal_days": 10,
    }

    cid = (await add(user_client, name="Podľa pravidla", url="pravidlo.sk"))["customer"]["id"]
    await user_client.post(f"/api/companies/{cid}/status", json={"status": "no_answer"})
    await age(app, cid, status_days=45)  # a month and a half: inside the default, past the new rule
    body = (await user_client.get("/api/companies")).json()
    assert body["archived"] == 1 and body["rules"]["archive_after_months"] == 1
    assert (await user_client.put("/api/settings/crm-rules", json={"archive_after_months": 0})).status_code == 422
