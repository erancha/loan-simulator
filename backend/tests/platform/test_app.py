"""The production wiring: the engine must list its tools before the app serves, and the app runs
on Postgres repositories and the Postgres checkpointer, here with a fake engine and model."""

import asyncio
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from auth_keys import CLIENT_ID, sign
from fakes import NOW, FakeLoanEngine, ScriptedChatModel
from loan_agent.adapters.postgres.repositories import (
    PostgresCheckEventStore,
    PostgresCheckRepository,
)
from loan_agent.domain.models import Check, Finances
from loan_agent.platform import app as app_module
from loan_agent.platform.api.auth import COOKIE
from loan_agent.platform.app import EngineUnreachableError, create_app
from loan_agent.platform.check_runner import FAILURE_MESSAGE
from loan_agent.platform.config import Settings
from loan_agent.platform.db import build_engine, session_factory

ENGINE_URL = "http://127.0.0.1:1/mcp"
ENGINE_TOKEN = "0123456789abcdef" * 3


def production_settings(public_key: Path, database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        llm_model="anthropic:claude-test",
        llm_api_key="sk-test",
        google_client_id=CLIENT_ID,
        engine_url=ENGINE_URL,
        engine_bearer_token=ENGINE_TOKEN,
        auth_public_key_file=public_key,
    )


def test_startup_fails_naming_the_engine_when_it_cannot_list_its_tools(
    public_key: Path,
) -> None:
    app = create_app(production_settings(public_key, "postgresql+psycopg://u:p@127.0.0.1:1/d"))
    with pytest.raises(EngineUnreachableError, match="127.0.0.1:1/mcp"), TestClient(app):
        pass


class StubEngine(FakeLoanEngine):
    """Stands in for McpLoanEngine: the fake's answers, and no tools of its own for the model."""

    opened: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, url: str, token: str) -> None:
        super().__init__()
        StubEngine.opened.append((url, token))

    async def model_tools(self) -> list[BaseTool]:
        return []


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch) -> ScriptedChatModel:
    """The production wiring with the engine and the chat model replaced by the returned
    ScriptedChatModel and a StubEngine; on teardown, checks both were built from the settings."""
    model = ScriptedChatModel(replies=[])
    built: list[tuple[str, str, str]] = []

    def build_chat_model(spec: str, api_key: str, kind: str) -> ScriptedChatModel:
        built.append((spec, api_key, kind))
        return model

    StubEngine.opened = []
    monkeypatch.setattr(app_module, "McpLoanEngine", StubEngine)
    monkeypatch.setattr(app_module, "build_chat_model", build_chat_model)
    yield model
    assert StubEngine.opened == [(ENGINE_URL, ENGINE_TOKEN)]
    assert built == [("anthropic:claude-test", "sk-test", "turn")]


async def seed_interrupted_turn(database_url: str, check_id: str) -> None:
    engine = build_engine(database_url)
    sessions = session_factory(engine)
    await PostgresCheckRepository(sessions).add(
        Check(check_id, "1001", NOW, None, None, None, None, Finances())
    )
    events = PostgresCheckEventStore(sessions)
    await events.append(check_id, "message.user", {"text": "שלום"})
    await events.append(check_id, "turn.status", {"status": "running"})
    await engine.dispose()


async def stored_types(database_url: str, check_id: str) -> list[tuple[str, Any]]:
    engine = build_engine(database_url)
    events = await PostgresCheckEventStore(session_factory(engine)).list(check_id, 0)
    await engine.dispose()
    return [(event.type, dict(event.data)) for event in events]


def test_the_app_serves_a_turn_on_postgres(
    pg_url: str, public_key: Path, stubbed: ScriptedChatModel
) -> None:
    asyncio.run(seed_interrupted_turn(pg_url, "c-interrupted"))
    stubbed.replies.extend(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "set_loan",
                        "args": {"purpose": "רכב", "amount": "70000"},
                        "id": "call-loan",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage("שמרתי"),
        ]
    )

    with TestClient(create_app(production_settings(public_key, pg_url))) as client:
        client.cookies.set(COOKIE, sign())
        assert client.get("/ready").json() == {"status": "ok"}
        check_id = client.post("/api/checks").json()["id"]
        sent = client.post(f"/api/checks/{check_id}/messages", json={"text": "יש לי 70,000"})
        assert sent.status_code == 202
        client.portal.call(client.app.state.runner.drain)  # type: ignore[attr-defined]

        view = client.get(f"/api/checks/{check_id}").json()
        assert (view["id"], view["loan"]) == (check_id, {"purpose": "רכב", "amount": "70000"})

    assert [event for event, _ in asyncio.run(stored_types(pg_url, check_id))] == [
        "message.user",
        "message.counted",
        "turn.status",
        "loan.set",
        "message.assistant",
        "turn.status",
    ]
    assert asyncio.run(stored_types(pg_url, "c-interrupted"))[2:] == [
        ("turn.failed", {"message": FAILURE_MESSAGE}),
        ("turn.status", {"status": "idle"}),
    ]
