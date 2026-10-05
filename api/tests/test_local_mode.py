"""Desktop app (local mode): token sign-in, loopback-only host, quit."""

from __future__ import annotations

import asyncio
import dataclasses

import httpx
from conftest import HEADERS

from webaudit_api.main import create_app


def _client(app, host: str = "127.0.0.1:8765") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{host}", headers=HEADERS)


async def test_token_sign_in_and_quit(settings) -> None:
    quit_calls: list[bool] = []
    local = dataclasses.replace(settings, local_mode=True, local_token="launch-token", signup_enabled=False)
    app = create_app(local, start_worker=False, on_quit=lambda: quit_calls.append(True))
    async with app.router.lifespan_context(app), _client(app) as client:
        assert (await client.get("/api/auth/me")).status_code == 401
        assert (await client.get("/api/auth/local", params={"token": "wrong"})).status_code == 404

        signed_in = await client.get("/api/auth/local", params={"token": "launch-token"})
        assert signed_in.status_code == 303 and signed_in.headers["location"] == "/"
        me = (await client.get("/api/auth/me")).json()
        assert me["local"] is True and me["workspace_name"] == "My workspace"

        # A second launch signs in as the same local user.
        await client.get("/api/auth/local", params={"token": "launch-token"})
        assert (await client.get("/api/auth/me")).json()["workspace_id"] == me["workspace_id"]

        # No passwords or sign-up in the desktop app.
        assert (await client.post("/api/auth/signup", json={"email": "a@b.sk", "password": "x" * 12})).status_code == 403

        assert (await client.post("/api/local/quit")).status_code == 204
        await asyncio.sleep(0.4)
        assert quit_calls == [True]


async def test_only_loopback_host_names_are_answered(settings) -> None:
    local = dataclasses.replace(settings, local_mode=True, local_token="t")
    app = create_app(local, start_worker=False)
    async with app.router.lifespan_context(app):
        async with _client(app, "evil.example:8765") as rebinding:
            assert (await rebinding.get("/api/health")).status_code == 400
        async with _client(app, "localhost:8765") as ok:
            assert (await ok.get("/api/health")).status_code == 200


async def test_local_endpoints_are_off_on_a_server(user_client: httpx.AsyncClient) -> None:
    assert (await user_client.get("/api/auth/local", params={"token": "anything"})).status_code == 404
    assert (await user_client.post("/api/local/quit")).status_code == 404
    assert (await user_client.get("/api/auth/me")).json()["local"] is False
