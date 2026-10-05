from __future__ import annotations

import sys

import httpx
import pytest
from conftest import signup
from sqlalchemy import select

from webaudit_api.models import ApiKey


async def test_signup_me_logout_login(client: httpx.AsyncClient) -> None:
    me = await signup(client)
    assert me["email"] == "designer@example.com" and me["workspace_name"] == "Studio"
    assert (await client.get("/api/auth/me")).json()["email"] == "designer@example.com"

    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401

    bad = await client.post("/api/auth/login", json={"email": "designer@example.com", "password": "nope"})
    assert bad.status_code == 401
    good = await client.post("/api/auth/login", json={"email": "Designer@Example.com ", "password": "correct horse battery"})
    assert good.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_signup_validation(client: httpx.AsyncClient) -> None:
    await signup(client)
    duplicate = await client.post("/api/auth/signup", json={"email": "designer@example.com", "password": "another long password"})
    assert duplicate.status_code == 409
    short = await client.post("/api/auth/signup", json={"email": "x@example.com", "password": "short"})
    assert short.status_code == 422


async def test_mutations_need_csrf_header(make_client) -> None:
    async with make_client() as c:
        c.headers.pop("X-Requested-With")
        response = await c.post("/api/auth/signup", json={"email": "a@b.sk", "password": "long enough password"})
    assert response.status_code == 403


async def test_session_cookie_is_httponly(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/auth/signup", json={"email": "c@d.sk", "password": "long enough password"})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


async def test_api_keys_are_encrypted_masked_and_testable(user_client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "AIzaSyTESTKEY-1234567890abcd"
    saved = await user_client.put("/api/settings/keys/pagespeed", json={"key": secret})
    assert saved.json() == {**saved.json(), "configured": True, "last4": "abcd"}

    settings = (await user_client.get("/api/settings")).json()
    assert settings["keys"]["pagespeed"]["configured"] is True
    assert secret not in str(settings)
    assert settings["keys"]["claude"]["configured"] is False

    async with app.state.sessionmaker() as db:
        row = await db.scalar(select(ApiKey))
        assert secret not in row.encrypted and app.state.keybox.decrypt(row.encrypted) == secret

    async def fake_test(service: str, key: str, base: str) -> tuple[bool, str]:
        assert key == secret and service == "pagespeed"
        return True, "Key is valid"

    monkeypatch.setattr("webaudit_api.routers.settings.test_key", fake_test)
    tested = await user_client.post("/api/settings/keys/pagespeed/test")
    assert tested.json()["test_ok"] is True and tested.json()["test_message"] == "Key is valid"

    removed = await user_client.put("/api/settings/keys/pagespeed", json={"key": ""})
    assert removed.json()["configured"] is False
    assert (await user_client.post("/api/settings/keys/pagespeed/test")).status_code == 400
    assert (await user_client.put("/api/settings/keys/unknown", json={"key": "x"})).status_code == 404


async def test_profile_round_trip(user_client: httpx.AsyncClient) -> None:
    body = {"name": "Matúš Web", "company_id": "12345678", "phone": "+421 900 000 000", "email": "me@studio.sk", "pdf_language": "cs"}
    out = (await user_client.put("/api/settings/profile", json=body)).json()
    assert out["profile"]["company_id"] == "12345678" and out["pdf_language"] == "cs"
    assert (await user_client.put("/api/settings/profile", json={**body, "pdf_language": "de"})).status_code == 422


async def test_claude_key_check_maps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import anthropic

    from webaudit_api import keys

    request = httpx.Request("GET", "https://api.anthropic.com/v1/models/x")

    class FakeModels:
        def __init__(self, exc: Exception | None) -> None:
            self.exc = exc

        async def retrieve(self, model: str) -> None:
            if self.exc:
                raise self.exc

    class FakeClient:
        exc: Exception | None = None

        def __init__(self, **_: object) -> None:
            self.models = FakeModels(FakeClient.exc)

        async def close(self) -> None:
            pass

    monkeypatch.setattr(keys.anthropic, "AsyncAnthropic", FakeClient)
    assert await keys.test_claude("k") == (True, "Key is valid")
    FakeClient.exc = anthropic.AuthenticationError("bad", response=httpx.Response(401, request=request), body=None)
    assert await keys.test_claude("k") == (False, "Key is not valid")


def test_secret_key_is_kept_in_the_data_folder(tmp_path, monkeypatch) -> None:
    from webaudit_api.settings import Settings

    monkeypatch.delenv("WEBAUDIT_SECRET_KEY", raising=False)
    monkeypatch.setenv("WEBAUDIT_DATA_DIR", str(tmp_path / "data"))
    first = Settings().secret_key
    if sys.platform != "win32":  # Windows has no POSIX permission bits
        assert (tmp_path / "data" / "secret.key").stat().st_mode & 0o777 == 0o600
    assert Settings().secret_key == first  # survives a restart
    monkeypatch.setenv("WEBAUDIT_SECRET_KEY", "from-env")
    assert Settings().secret_key == "from-env"
