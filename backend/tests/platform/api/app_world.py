"""An app wired through its production lifespan to in-memory storage, a fake engine, a scripted
model and an in-memory checkpointer, with Dana's signed token as the session cookie."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from auth_keys import CLIENT_ID, sign
from fakes import (
    NOW,
    PRIME_SIMULATION,
    PRIME_TRACK,
    Clock,
    FakeLoanEngine,
    InMemoryCheckEventStore,
    InMemoryCheckRepository,
    InMemoryOptionRepository,
    InMemoryProfileRepository,
    InMemoryRecommendationRepository,
    ScriptedChatModel,
)
from loan_agent.domain.models import Check, Goal, Option, Profile, Recommendation, User
from loan_agent.platform.api.auth import COOKIE
from loan_agent.platform.app import create_app
from loan_agent.platform.checkpointer import checkpoint_serde
from loan_agent.platform.config import Settings
from loan_agent.platform.dependencies import Infrastructure

DANA = User("1001", "dana@example.com", "Dana")
OMER = User("2002", "omer@example.com", "Omer")
DANA_TOKEN = sign()
OMER_TOKEN = sign(sub=OMER.id, email=OMER.email, name=OMER.name)

GOAL = Goal("רכב משפחתי", Decimal(120000))
FULL_PROFILE = Profile(
    net_fixed_income=Decimal(14000),
    variable_income=Decimal(2000),
    variable_income_minimum=Decimal(0),
    fixed_expenses=Decimal(6500),
    existing_loan_payments=Decimal(800),
    savings=Decimal(70000),
)


def app_settings(public_key: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@127.0.0.1:1/d",
        "llm_model": "anthropic:claude-test",
        "llm_api_key": "sk-test",
        "google_client_id": CLIENT_ID,
        "engine_url": "http://127.0.0.1:1/mcp",
        "engine_bearer_token": "0123456789abcdef" * 3,
        "auth_public_key_file": public_key,
    }
    return Settings(**(values | overrides))


@dataclass
class World:
    clock: Clock = field(default_factory=Clock)
    model: ScriptedChatModel = field(default_factory=lambda: ScriptedChatModel(replies=[]))
    engine: FakeLoanEngine = field(default_factory=FakeLoanEngine)
    engine_tools: list[BaseTool] = field(default_factory=list)
    saver: InMemorySaver = field(default_factory=lambda: InMemorySaver(serde=checkpoint_serde()))
    checks: InMemoryCheckRepository = field(default_factory=InMemoryCheckRepository)
    options: InMemoryOptionRepository = field(default_factory=InMemoryOptionRepository)
    recommendations: InMemoryRecommendationRepository = field(
        default_factory=InMemoryRecommendationRepository
    )
    database_error: Exception | None = None
    """Raised by the readiness probe when set."""

    def __post_init__(self) -> None:
        self.profiles = InMemoryProfileRepository(self.clock)
        self.events = InMemoryCheckEventStore(self.checks, self.clock)

    def replies(self, *messages: AIMessage) -> None:
        self.model.replies.extend(messages)

    @asynccontextmanager
    async def infrastructure(self, settings: Settings) -> AsyncIterator[Infrastructure]:
        yield Infrastructure(
            profiles=self.profiles,
            checks=self.checks,
            options=self.options,
            recommendations=self.recommendations,
            events=self.events,
            engine=self.engine,
            engine_tools=self.engine_tools,
            model=self.model,
            checkpointer=self.saver,
            ready=self._ready,
            clock=self.clock,
        )

    async def _ready(self) -> None:
        if self.database_error is not None:
            raise self.database_error

    def app(self, public_key: Path, **settings: Any) -> FastAPI:
        return create_app(app_settings(public_key, **settings), self.infrastructure)

    @contextmanager
    def client(
        self, public_key: Path, token: str | None = DANA_TOKEN, **settings: Any
    ) -> Iterator[TestClient]:
        """token None leaves the client signed out."""
        with TestClient(self.app(public_key, **settings)) as client:
            if token is not None:
                client.cookies.set(COOKIE, token)
            yield client

    def drain(self, client: TestClient) -> None:
        """Wait in the app's event loop until no turn is in flight."""
        app = client.app
        assert isinstance(app, FastAPI)
        client.portal.call(app.state.runner.drain)  # type: ignore[union-attr]


def seed_recommended_check(world: World, check_id: str = "c-rec") -> None:
    """Dana's check with a goal, one priced option and a recommendation computed from her
    profile as saved at NOW."""
    world.profiles.rows[DANA.id] = (FULL_PROFILE, NOW)
    world.checks.rows[check_id] = Check(check_id, DANA.id, NOW, GOAL, NOW)
    world.options.rows[check_id] = [
        Option(
            id="o1",
            check_id=check_id,
            loan={"tracks": [PRIME_TRACK]},
            source="offer",
            lender="בנק הפועלים",
            offer_date=NOW.date(),
            summary=PRIME_SIMULATION.figures,
            created_at=NOW,
        )
    ]
    world.recommendations.rows[check_id] = Recommendation(
        check_id=check_id,
        preferred_option_id="o1",
        alternative_option_id=None,
        reasoning="ההחזר החודשי נמוך מהתקרה",
        loan_amount=Decimal("80000.00"),
        payment_ceiling=Decimal("4700.00"),
        min_cushion=Decimal("18000.00"),
        cushion_kept=Decimal("30000.00"),
        created_at=NOW,
    )
