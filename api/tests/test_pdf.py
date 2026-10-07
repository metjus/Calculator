"""Stage 5: the client PDF — the preview, the export and the logo in Settings.

The export really renders with Chromium, so it is skipped where no browser is available.
"""

from __future__ import annotations

import io

import httpx
import pytest
from test_audits import make_worker

from webaudit_api.models import Workspace

needs_browser = pytest.mark.skipif(
    __import__("shutil").which("chromium") is None and not __import__("os").environ.get("WEBAUDIT_CHROMIUM_PATH"),
    reason="no Chromium for Playwright",
)

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def scored_site(user_client: httpx.AsyncClient, app, sites) -> tuple[int, int]:
    created = (await user_client.post("/api/audits", json={"project": "Salóny", "urls": sites.urls["legacy"]})).json()
    audit_id = created["audit"]["id"]
    await make_worker(app, sites).run_once()
    site = (await user_client.get(f"/api/audits/{audit_id}")).json()["sites"][0]
    assert site["state"] == "ok"
    return audit_id, site["id"]


async def test_preview_offers_everything_the_operator_then_edits(user_client: httpx.AsyncClient, app, sites) -> None:
    await user_client.put(
        "/api/settings/profile",
        json={"name": "Matúš Š.", "company_id": "12345678", "phone": "+421 900 123 456", "email": "me@studio.sk", "pdf_language": "sk"},
    )
    audit_id, site_id = await scored_site(user_client, app, sites)
    url = f"/api/audits/{audit_id}/sites/{site_id}/pdf-preview"

    body = (await user_client.get(url)).json()
    assert body["language"] == "sk" and body["languages"] == ["sk", "cs", "en"]
    assert body["issues"] and all({"id", "label", "problem", "impact", "solution"} <= set(i) for i in body["issues"])
    assert "Čo je zle" not in body["issues"][0]["problem"]  # the part headings are the PDF's, not the text's
    assert len(body["offer"]) == 3 and body["offer"][1]["recommended"] is True
    assert all(option["price"] == "" for option in body["offer"])  # prices are typed by hand
    assert body["profile"]["name"] == "Matúš Š." and body["has_logo"] is False
    assert body["file_name"].endswith(".pdf") and body["summary"]

    czech = (await user_client.get(url, params={"lang": "cs"})).json()
    assert czech["language"] == "cs" and czech["issues"][0]["label"] != body["issues"][0]["label"]


@needs_browser
async def test_export_renders_a_pdf_and_remembers_the_prices(user_client: httpx.AsyncClient, app, sites) -> None:
    audit_id, site_id = await scored_site(user_client, app, sites)
    preview = (await user_client.get(f"/api/audits/{audit_id}/sites/{site_id}/pdf-preview")).json()
    offer = preview["offer"]
    for option, price in zip(offer, ("180 €", "540 €", "od 900 €"), strict=True):
        option["price"] = price

    response = await user_client.post(
        f"/api/audits/{audit_id}/sites/{site_id}/pdf",
        json={
            "language": "sk",
            "client_name": "Kaderníctvo Lena",
            "summary": "Vlastné zhrnutie.",
            "include": [preview["issues"][0]["id"]],
            "offer": offer,
        },
    )
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-") and len(response.content) > 20_000
    assert ".pdf" in response.headers["content-disposition"]

    async with app.state.sessionmaker() as db:
        workspace = await db.scalar(__import__("sqlalchemy").select(Workspace))
        assert [o["price"] for o in workspace.pdf_offer] == ["180 €", "540 €", "od 900 €"]

    again = (await user_client.get(f"/api/audits/{audit_id}/sites/{site_id}/pdf-preview")).json()
    assert [o["price"] for o in again["offer"]] == ["180 €", "540 €", "od 900 €"]  # prefilled next time


async def test_a_website_without_a_score_has_no_report(user_client: httpx.AsyncClient, app, sites) -> None:
    created = (await user_client.post("/api/audits", json={"urls": sites.urls["cloudflare"]})).json()
    audit_id = created["audit"]["id"]
    await make_worker(app, sites).run_once()
    site = (await user_client.get(f"/api/audits/{audit_id}")).json()["sites"][0]
    assert site["state"] == "protected"
    refused = await user_client.get(f"/api/audits/{audit_id}/sites/{site['id']}/pdf-preview")
    assert refused.status_code == 422 and "no score" in refused.text


async def test_the_logo_is_saved_for_the_pdf_header(user_client: httpx.AsyncClient, app, settings) -> None:
    files = {"file": ("logo.png", io.BytesIO(PNG), "image/png")}
    saved = await user_client.put("/api/settings/logo", files=files)
    assert saved.status_code == 200 and saved.json()["logo"] is True
    assert (settings.data_dir / "branding" / "logo.png").is_file()
    assert (await user_client.get("/api/settings/logo")).status_code == 200

    refused = await user_client.put("/api/settings/logo", files={"file": ("logo.txt", io.BytesIO(b"x"), "text/plain")})
    assert refused.status_code == 422

    removed = await user_client.delete("/api/settings/logo")
    assert removed.status_code == 200 and removed.json()["logo"] is False
    assert not (settings.data_dir / "branding" / "logo.png").exists()
    assert (await user_client.get("/api/settings/logo")).status_code == 404
