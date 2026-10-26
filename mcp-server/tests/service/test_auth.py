from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx2
import pytest

from loan_engine.domain.history import MarketHistory
from loan_engine.service.config import Settings
from loan_engine.service.server import build_app, build_server

LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}

HttpClient = Callable[[str], AbstractAsyncContextManager[httpx2.AsyncClient]]


@pytest.fixture
def http_client(settings: Settings, history: MarketHistory) -> HttpClient:
    """A client of the running app that sends requests with the given Host."""
    app = build_app(build_server(settings, lambda: history), settings)

    @asynccontextmanager
    async def connect(host: str) -> AsyncIterator[httpx2.AsyncClient]:
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url=f"http://{host}"
            ) as client,
        ):
            yield client

    return connect


def bearer(token: str) -> dict[str, str]:
    return {**MCP_HEADERS, "authorization": f"Bearer {token}"}


async def test_missing_or_wrong_bearer_is_401(http_client: HttpClient, settings: Settings) -> None:
    async with http_client(settings.allowed_hosts[0]) as client:
        missing = await client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS)
        wrong = await client.post("/mcp", json=LIST_TOOLS, headers=bearer("w" * 32))
    for response in (missing, wrong):
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Bearer")


async def test_valid_bearer_lists_tools(http_client: HttpClient, settings: Settings) -> None:
    token = settings.bearer_token.get_secret_value()
    async with http_client(settings.allowed_hosts[0]) as client:
        response = await client.post("/mcp", json=LIST_TOOLS, headers=bearer(token))
    assert response.status_code == 200, response.text
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert "simulate_loan" in names


async def test_unlisted_host_is_rejected(http_client: HttpClient, settings: Settings) -> None:
    token = settings.bearer_token.get_secret_value()
    async with http_client("attacker.example:8020") as client:
        response = await client.post("/mcp", json=LIST_TOOLS, headers=bearer(token))
    assert response.status_code == 421
