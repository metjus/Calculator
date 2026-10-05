from __future__ import annotations

import importlib.util
import ssl
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from webaudit_api.main import create_app
from webaudit_api.settings import Settings

# Reuse the core's local fixture websites (no internet in CI containers).
CORE_TESTS = Path(__file__).resolve().parents[2] / "core" / "tests"
sys.path.insert(0, str(CORE_TESTS))
_spec = importlib.util.spec_from_file_location("core_test_fixtures", CORE_TESTS / "conftest.py")
_core_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core_fixtures)
FixtureServers = _core_fixtures.FixtureServers

HEADERS = {"X-Requested-With": "webaudit"}


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(scope="session")
def sites() -> FixtureServers:
    import trustme

    servers = FixtureServers()
    ca = trustme.CA()
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert("127.0.0.1").configure_cert(server_ctx)
    servers.ca = ca
    servers.start("modern", "127.0.0.1", tls_context=server_ctx)
    servers.start("legacy", "127.0.0.2")
    servers.start("cloudflare", "127.0.0.3")
    yield servers
    servers.stop()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        secret_key="test-secret",
        data_dir=tmp_path / "data",
        inprocess_worker=False,
        allow_private_targets=True,
        cookie_secure=False,
    )


@pytest.fixture
async def app(settings: Settings):
    application = create_app(settings, start_worker=False)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
def make_client(app) -> Callable[[], httpx.AsyncClient]:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers=HEADERS)

    return factory


@pytest.fixture
async def client(make_client) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client() as c:
        yield c


async def signup(client: httpx.AsyncClient, email: str = "designer@example.com") -> dict:
    response = await client.post("/api/auth/signup", json={"email": email, "password": "correct horse battery", "workspace_name": "Studio"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def user_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    await signup(client)
    return client
