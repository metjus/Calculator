from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from webaudit_api.models import Company
from webaudit_api.search.providers import Area, Overpass

TRNAVA = {"label": "Trnava, Trnavský kraj, Slovensko", "lat": 48.3774, "lon": 17.5872, "kind": "place"}

PHOTON = {
    "features": [
        {
            "geometry": {"coordinates": [17.5872, 48.3774]},
            "properties": {
                "osm_type": "R",
                "osm_id": 388264,
                "type": "city",
                "name": "Trnava",
                "county": "okres Trnava",
                "state": "Trnavský kraj",
                "country": "Slovensko",
                "countrycode": "SK",
                "extent": [17.5, 48.42, 17.68, 48.33],
            },
        },
        {
            "geometry": {"coordinates": [17.6, 48.4]},
            "properties": {
                "osm_type": "R",
                "osm_id": 388265,
                "type": "county",
                "name": "okres Trnava",
                "state": "Trnavský kraj",
                "country": "Slovensko",
                "countrycode": "SK",
                "extent": [17.3, 48.6, 17.9, 48.2],
            },
        },
        {
            "geometry": {"coordinates": [15.0, 49.0]},
            "properties": {
                "osm_type": "N",
                "osm_id": 1,
                "type": "city",
                "name": "Trnava",
                "state": "Zlínský kraj",
                "country": "Česko",
                "countrycode": "CZ",
            },
        },
    ]
}

GOOGLE = {
    "places": [
        {
            "id": "g1",
            "displayName": {"text": "Kaderníctvo Lena"},
            "location": {"latitude": 48.378, "longitude": 17.588},
            "websiteUri": "https://www.lena-example.sk/",
            "primaryTypeDisplayName": {"text": "Hair salon"},
        },
        {
            "id": "g2",
            "displayName": {"text": "Salón Bez Webu s.r.o."},
            "location": {"latitude": 48.379, "longitude": 17.59},
            "primaryTypeDisplayName": {"text": "Hair salon"},
        },
        {"id": "g3", "displayName": {"text": "Far Away Salon"}, "location": {"latitude": 48.9, "longitude": 18.4}},
    ]
}

OVERPASS = {
    "elements": [
        # Same business as g1 (same domain) -> merged.
        {
            "type": "node",
            "id": 11,
            "lat": 48.3781,
            "lon": 17.5881,
            "tags": {"name": "Lena", "shop": "hairdresser", "website": "lena-example.sk", "phone": "+421 900 000 000"},
        },
        # Same as g2 by name and position -> merged; OSM name becomes storable.
        {"type": "way", "id": 12, "center": {"lat": 48.3791, "lon": 17.5901}, "tags": {"name": "Salón bez webu", "shop": "hairdresser"}},
        {
            "type": "node",
            "id": 13,
            "lat": 48.37,
            "lon": 17.58,
            "tags": {"name": "Barber OSM", "shop": "hairdresser", "contact:website": "https://barber.example.sk"},
        },
    ]
}


@pytest.fixture
def calls() -> list[httpx.Request]:
    return []


@pytest.fixture(autouse=True)
def fake_services(app, calls: list[httpx.Request]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "photon" in request.url.host:
            return httpx.Response(200, json=PHOTON)
        if "overpass" in request.url.host:
            return httpx.Response(200, json=OVERPASS)
        if "places.googleapis.com" in request.url.host:
            return httpx.Response(200, json=GOOGLE)
        return httpx.Response(404)

    app.state.search_transport = httpx.MockTransport(handler)


async def test_options_and_areas_are_country_restricted(user_client: httpx.AsyncClient) -> None:
    options = (await user_client.get("/api/search/options")).json()
    assert {"code": "sk", "name": "Slovakia", "language": "sk"} in options["countries"]
    assert any(c["id"] == "hair_salon" for c in options["categories"])
    assert options["google_configured"] is False
    assert options["map_tile_url"] == "/api/search/tiles/{z}/{x}/{y}?source=osm" and options["map_source"] == "osm"
    assert "OpenStreetMap" in options["map_attribution"]

    areas = (await user_client.get("/api/search/areas", params={"country": "sk", "q": "Trnava"})).json()
    assert [a["label"] for a in areas] == ["Trnava, okres Trnava, Trnavský kraj, Slovensko", "okres Trnava, Trnavský kraj, Slovensko"]
    assert areas[1]["kind"] == "region" and areas[1]["osm_relation"] == 388265
    assert areas[0]["bbox"] == [17.5, 48.33, 17.68, 48.42]
    assert (await user_client.get("/api/search/areas", params={"country": "xx", "q": "Trnava"})).status_code == 422


async def test_search_without_google_key_uses_osm_only(user_client: httpx.AsyncClient, calls: list[httpx.Request]) -> None:
    estimate = (await user_client.post("/api/search/estimate", json={"country": "sk", "area": TRNAVA, "category_id": "hair_salon"})).json()
    assert estimate["google_configured"] is False and estimate["estimated_cost_usd"] == 0

    result = (
        await user_client.post("/api/search/run", json={"country": "sk", "area": TRNAVA, "radius_km": 10, "category_id": "hair_salon"})
    ).json()
    assert result["sources"] == {"google": 0, "osm": 3}
    assert result["counts"] == {"total": 3, "with_website": 2, "without_website": 1}
    assert result["attribution"].startswith("©")
    assert any("Google Places skipped" in w for w in result["warnings"])
    assert not any("places.googleapis.com" in str(r.url) for r in calls)
    assert "phone" not in json.dumps(result) and "+421" not in json.dumps(result)


async def test_search_with_google_merges_and_counts_usage(user_client: httpx.AsyncClient, calls: list[httpx.Request]) -> None:
    await user_client.put("/api/settings/keys/google_places", json={"key": "AIza-google-key"})
    body = {"country": "sk", "area": TRNAVA, "radius_km": 15, "category_id": "hair_salon"}
    estimate = (await user_client.post("/api/search/estimate", json=body)).json()
    assert estimate["google_requests_max"] == 3 and estimate["over_free_limit"] is False

    result = (await user_client.post("/api/search/run", json=body)).json()
    google_calls = [r for r in calls if "places.googleapis.com" in r.url.host]
    assert len(google_calls) == 1  # no nextPageToken -> one page
    sent = json.loads(google_calls[0].content)
    assert sent["includedType"] == "hair_salon" and sent["regionCode"] == "SK" and sent["textQuery"] == "kaderníctvo"
    assert "rectangle" in sent["locationRestriction"]
    assert google_calls[0].headers["X-Goog-FieldMask"].count("Phone") == 0

    by_name = {r["name"]: r for r in result["results"]}
    assert set(by_name) == {"Kaderníctvo Lena", "Salón Bez Webu s.r.o.", "Barber OSM"}  # g3 is outside the radius
    lena = by_name["Kaderníctvo Lena"]
    assert lena["sources"] == ["google", "osm"] and lena["place_id"] == "g1" and lena["osm_id"] == "node/11"
    assert by_name["Salón Bez Webu s.r.o."]["osm_name"] == "Salón bez webu"
    assert result["counts"]["without_website"] == 1

    after = (await user_client.post("/api/search/estimate", json=body)).json()
    assert after["used_this_month"] == 1


async def test_send_results_to_audit_and_leads(user_client: httpx.AsyncClient, app) -> None:
    sent = await user_client.post(
        "/api/search/to-audit",
        json={
            "project": "Kaderníctva Trnava",
            "items": [
                {"website": "https://www.lena-example.sk/", "place_id": "g1"},
                {"website": "https://barber.example.sk", "osm_id": "node/13", "osm_name": "Barber OSM"},
            ],
        },
    )
    assert sent.status_code == 201 and sent.json()["audit"]["total"] == 2
    leads = await user_client.post(
        "/api/search/to-leads",
        json={"project": "Kaderníctva Trnava", "items": [{"place_id": "g2", "osm_id": "way/12", "osm_name": "Salón bez webu"}]},
    )
    assert leads.json() == {"leads": 1}
    async with app.state.sessionmaker() as db:
        companies = list(await db.scalars(select(Company).order_by(Company.id)))
    lena, barber, lead = companies
    assert lena.name is None and lena.place_id == "g1"  # Google names are not stored
    assert barber.name == "Barber OSM" and lead.url is None and lead.name == "Salón bez webu"

    # Known companies are marked in later searches.
    result = (await user_client.post("/api/search/run", json={"country": "sk", "area": TRNAVA, "category_id": "hair_salon"})).json()
    marked = {r["name"]: r["known"] for r in result["results"]}
    assert marked["Barber OSM"]["company_id"] == barber.id
    assert marked["Salón bez webu"]["company_id"] == lead.id


async def test_templates_and_validation(user_client: httpx.AsyncClient) -> None:
    params = {"country": "sk", "area": TRNAVA, "radius_km": 15, "category_id": "car_repair"}
    saved = (await user_client.post("/api/search/templates", json={"name": "Autoservisy Trnava + 15 km", "params": params})).json()
    templates = (await user_client.get("/api/search/templates")).json()
    assert templates[0]["name"] == "Autoservisy Trnava + 15 km" and templates[0]["params"]["radius_km"] == 15
    assert (await user_client.delete(f"/api/search/templates/{saved['id']}")).status_code == 204

    for bad in (
        {"country": "", "area": TRNAVA, "category_id": "hair_salon"},
        {"country": "sk", "area": TRNAVA},
        {"country": "sk", "area": TRNAVA, "category_id": "hair_salon", "radius_km": 80},
        {"country": "sk", "area": TRNAVA, "category_id": "hair_salon", "mode": "region"},
    ):
        assert (await user_client.post("/api/search/run", json=bad)).status_code == 422


def test_overpass_query_shapes() -> None:
    circle = Overpass.build_query(Area("x", 48.0, 17.0, radius_km=10), [["shop", "hairdresser"]], None)
    assert "(around:10000,48.000000,17.000000)" in circle and 'nwr["shop"="hairdresser"]' in circle
    region = Overpass.build_query(Area("okres", 48.0, 17.0, osm_relation=388265), [["shop", "hairdresser"]], "Kader")
    assert "area(id:3600388265)" in region and '["name"~"Kader",i]' in region


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
OSM_BLOCKED = b"<html>Access blocked</html>"


async def test_overpass_falls_back_to_the_next_server(app, user_client: httpx.AsyncClient, calls: list[httpx.Request]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "overpass-api.de":
            return httpx.Response(429, text="rate_limited")
        if request.url.host == "overpass.private.coffee":
            return httpx.Response(504, text="Gateway Timeout")
        if request.url.host == "maps.mail.ru":
            return httpx.Response(200, json=OVERPASS)
        return httpx.Response(404)

    app.state.search_transport = httpx.MockTransport(handler)
    body = {"country": "sk", "area": TRNAVA, "radius_km": 10, "category_id": "hair_salon", "sources": ["osm"]}
    result = (await user_client.post("/api/search/run", json=body)).json()
    assert result["sources"]["osm"] == 3 and result["warnings"] == []
    assert [r.url.host for r in calls] == ["overpass-api.de", "overpass.private.coffee", "maps.mail.ru"]
    assert calls[0].headers["User-Agent"].startswith("WebAudit/") and "github.com" in calls[0].headers["User-Agent"]

    def down(request: httpx.Request) -> httpx.Response:
        if request.url.host == "maps.mail.ru":
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(503, text="busy")

    app.state.search_transport = httpx.MockTransport(down)
    result = (await user_client.post("/api/search/run", json=body)).json()
    assert result["sources"]["osm"] == 0
    (warning,) = result["warnings"]
    assert "overpass-api.de: HTTP 503" in warning and "maps.mail.ru: ConnectTimeout" in warning


async def test_map_tiles_are_fetched_once_and_cached(app, settings, user_client: httpx.AsyncClient, make_client) -> None:
    tile_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tile_calls.append(request)
        if request.url.path == "/11/1123/711.png":
            return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
        return httpx.Response(403, content=OSM_BLOCKED, headers={"Content-Type": "text/html"})

    app.state.search_transport = httpx.MockTransport(handler)
    first = await user_client.get("/api/search/tiles/11/1123/711")
    assert first.status_code == 200 and first.content == PNG and first.headers["content-type"] == "image/png"
    assert "max-age" in first.headers["cache-control"]
    assert str(tile_calls[0].url) == "https://tile.openstreetmap.org/11/1123/711.png"
    assert tile_calls[0].headers["User-Agent"].startswith("WebAudit/")
    assert (settings.data_dir / "tiles" / "11" / "1123" / "711").read_bytes() == PNG

    again = await user_client.get("/api/search/tiles/11/1123/711")
    assert again.content == PNG and len(tile_calls) == 1  # served from the cache

    blocked = await user_client.get("/api/search/tiles/11/1124/711")  # a block page is never served as a tile
    assert blocked.status_code == 502 and blocked.json()["detail"] == "tile.openstreetmap.org refused the map tiles (HTTP 403)"
    assert (await user_client.get("/api/search/tiles/2/4/0")).status_code == 404
    assert (await user_client.get("/api/search/tiles/19/0/0")).status_code == 404
    async with make_client() as anonymous:
        assert (await anonymous.get("/api/search/tiles/11/1123/711")).status_code == 401


async def test_map_tiles_from_mapy_with_a_saved_key(app, settings, user_client: httpx.AsyncClient) -> None:
    mapy_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        mapy_calls.append(request)
        if request.url.host == "api.mapy.com" and request.url.params.get("apikey") == "mapy-key-1234":
            return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
        return httpx.Response(401, json={"message": "invalid key"})

    app.state.search_transport = httpx.MockTransport(handler)
    await user_client.put("/api/settings/keys/mapy", json={"key": "mapy-key-1234"})
    tested = (await user_client.post("/api/settings/keys/mapy/test")).json()
    assert tested["test_ok"] is True and tested["last4"] == "1234"
    assert mapy_calls[-1].url.path == "/v1/maptiles/basic/256/0/0/0"

    options = (await user_client.get("/api/search/options")).json()
    assert options["map_source"] == "mapy" and options["map_tile_url"].endswith("?source=mapy")
    assert "Seznam.cz" in options["map_attribution"] and "mapy-key" not in json.dumps(options)

    tile = await user_client.get("/api/search/tiles/11/1123/711", params={"source": "mapy"})
    assert tile.status_code == 200 and tile.content == PNG
    assert mapy_calls[-1].url.path == "/v1/maptiles/basic/256/11/1123/711"
    assert not (settings.data_dir / "tiles").exists()  # Mapy.com tiles are not stored

    await user_client.put("/api/settings/keys/mapy", json={"key": "wrong-key"})
    refused = await user_client.get("/api/search/tiles/11/1123/711")
    assert refused.status_code == 502 and refused.json()["detail"] == "Mapy.com did not accept the key saved in Settings"
    assert "wrong-key" not in refused.text
    assert (await user_client.post("/api/settings/keys/mapy/test")).json()["test_message"] == "Key is not valid"
