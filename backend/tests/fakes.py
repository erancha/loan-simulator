"""In-memory test doubles for the application's ports.

Core building blocks:
- InMemoryProfileRepository, InMemoryCheckRepository, InMemoryOptionRepository,
  InMemoryRecommendationRepository: dict-backed storage
- FakeLoanEngine: answers with values captured from the real engine (adapters/fixtures/engine),
  overridable per test, and records its calls
- InMemoryCheckEventStore: the per-check event log, stamped by the given clock
- RecordingSink: records stored and live events
- ScriptedChatModel: a chat model that answers with predefined messages in order, streaming each
  one's text in fragments followed by its tool calls, and records what it was given
"""

import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from loan_agent.domain.errors import CheckNotFoundError
from loan_agent.domain.models import Check, Goal, Option, OptionFigures, Profile, Recommendation
from loan_agent.ports.engine import Bounds, EngineError, Simulation, Sizing
from loan_agent.ports.repositories import CheckIds, EventTimes, StoredEvent

PRIME_TRACK = {
    "principal": "80000",
    "term_months": 48,
    "rate_kind": "prime",
    "prime_spread": "1.5",
    "cpi_linked": False,
    "method": "spitzer",
}
# The tools the engine in mcp-server/ lists.
ENGINE_TOOL_NAMES = {"assess_affordability", "size_loan", "simulate_loan", "suggest_tracks"}
ENGINE_FIXTURES = Path(__file__).parent / "adapters" / "fixtures" / "engine"
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


def engine_fixture(name: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((ENGINE_FIXTURES / f"{name}.json").read_text())
    return result


ASSESSED_BOUNDS = Bounds(
    payment_ceiling=Decimal("4700.00"),
    min_cushion=Decimal("18000.00"),
    reasons=(
        "variable_income_half_counted",
        "ceiling_by_disposable_income",
        "existing_loans_deducted",
    ),
)
SIZED_LOAN = Sizing(
    loan_amount=Decimal("80000.00"),
    savings_used=Decimal("40000.00"),
    cushion_kept=Decimal("30000.00"),
    spare_savings=Decimal("0.00"),
)
PRIME_SIMULATION = Simulation(
    figures=OptionFigures(
        first_payment=Decimal("1887.99"),
        peak_payment=Decimal("1887.99"),
        worst_peak_payment=Decimal("2038.63"),
        worst_start=date(2022, 4, 1),
        worst_end=date(2026, 3, 1),
        balloon_due=None,
        total_paid=Decimal("90623.31"),
        rate_as_of=date(2026, 10, 26),
        cpi_as_of=date(2026, 9, 1),
    ),
    structured=engine_fixture("simulate_loan_unlinked_prime"),
)
BALLOON_SIMULATION = Simulation(
    figures=OptionFigures(
        first_payment=Decimal("1273.80"),
        peak_payment=Decimal("1376.53"),
        worst_peak_payment=Decimal("1482.61"),
        worst_start=date(2021, 5, 1),
        worst_end=date(2025, 4, 1),
        balloon_due=Decimal("32472.96"),
        total_paid=Decimal("96049.73"),
        rate_as_of=date(2026, 10, 26),
        cpi_as_of=date(2026, 9, 1),
    ),
    structured=engine_fixture("simulate_loan_linked_balloon"),
)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class Ids:
    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._count = 0

    def __call__(self) -> str:
        self._count += 1
        return f"{self._prefix}-{self._count}"


class InMemoryProfileRepository:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self.rows: dict[str, tuple[Profile, datetime]] = {}

    async def get(self, user_id: str) -> tuple[Profile, datetime | None]:
        if user_id not in self.rows:
            return Profile(), None
        return self.rows[user_id]

    async def save(self, user_id: str, profile: Profile) -> datetime:
        saved_at = self._clock()
        self.rows[user_id] = (profile, saved_at)
        return saved_at


class InMemoryCheckRepository:
    def __init__(self) -> None:
        self.rows: dict[str, Check] = {}

    async def add(self, check: Check) -> None:
        self.rows[check.id] = check

    async def get(self, user_id: str, check_id: str) -> Check:
        check = self.rows.get(check_id)
        if check is None or check.user_id != user_id:
            raise CheckNotFoundError(check_id)
        return check

    async def list(self, user_id: str) -> list[Check]:
        mine = [check for check in self.rows.values() if check.user_id == user_id]
        return sorted(mine, key=lambda check: check.created_at, reverse=True)

    async def set_goal(self, check_id: str, goal: Goal) -> None:
        self.rows[check_id] = replace(self.rows[check_id], goal=goal)

    async def snapshot_profile(self, check_id: str, at: datetime) -> None:
        self.rows[check_id] = replace(self.rows[check_id], profile_snapshot_at=at)


class InMemoryOptionRepository:
    def __init__(self) -> None:
        self.rows: dict[str, list[Option]] = {}

    async def add(self, option: Option) -> None:
        self.rows.setdefault(option.check_id, []).append(option)

    async def list(self, check_id: str) -> list[Option]:
        return list(self.rows.get(check_id, []))

    async def get(self, check_id: str, option_id: str) -> Option:
        for option in self.rows.get(check_id, []):
            if option.id == option_id:
                return option
        raise KeyError(option_id)


class InMemoryRecommendationRepository:
    def __init__(self) -> None:
        self.rows: dict[str, Recommendation] = {}

    async def save(self, recommendation: Recommendation) -> None:
        self.rows[recommendation.check_id] = recommendation

    async def latest(self, check_id: str) -> Recommendation | None:
        return self.rows.get(check_id)


class InMemoryCheckEventStore:
    def __init__(self, checks: InMemoryCheckRepository, clock: Callable[[], datetime]) -> None:
        self._checks = checks
        self._clock = clock
        self.rows: dict[str, list[StoredEvent]] = {}

    async def append(self, check_id: str, type: str, data: Mapping[str, object]) -> int:
        if check_id not in self._checks.rows:
            raise CheckNotFoundError(check_id)
        log = self.rows.setdefault(check_id, [])
        log.append(StoredEvent(len(log) + 1, type, data, self._clock()))
        return len(log)

    async def list(self, check_id: str, after_seq: int) -> list[StoredEvent]:
        return [event for event in self.rows.get(check_id, []) if event.seq > after_seq]

    async def count_since(self, user_id: str, type: str, since: datetime) -> tuple[int, EventTimes]:
        times = sorted(
            event.created_at
            for check_id, log in self.rows.items()
            if self._checks.rows[check_id].user_id == user_id
            for event in log
            if event.type == type and event.created_at > since
        )
        return len(times), times

    async def checks_ending_with(self, type: str, data: Mapping[str, object]) -> CheckIds:
        return sorted(
            check_id
            for check_id, log in self.rows.items()
            if log and (log[-1].type, log[-1].data) == (type, data)
        )


@dataclass
class FakeLoanEngine:
    """simulations are answered in order; simulate_error, when set, is raised instead."""

    bounds: Bounds = ASSESSED_BOUNDS
    sizing: Sizing = SIZED_LOAN
    simulations: list[Simulation] = field(default_factory=list)
    simulate_error: EngineError | None = None
    calls: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    async def assess(self, profile: Mapping[str, object]) -> Bounds:
        self.calls.append(("assess", profile))
        return self.bounds

    async def size(
        self, goal_price: Decimal, trade_in_value: Decimal, savings: Decimal, min_cushion: Decimal
    ) -> Sizing:
        self.calls.append(
            (
                "size",
                {
                    "goal_price": goal_price,
                    "trade_in_value": trade_in_value,
                    "savings": savings,
                    "min_cushion": min_cushion,
                },
            )
        )
        return self.sizing

    async def simulate(self, loan: Mapping[str, object]) -> Simulation:
        self.calls.append(("simulate", loan))
        if self.simulate_error is not None:
            raise self.simulate_error
        return self.simulations.pop(0)

    async def suggest(self, principal: Decimal, term_months: int) -> list[Mapping[str, object]]:
        tracks: list[Mapping[str, object]] = engine_fixture("suggest_tracks")["tracks"]
        return tracks


@dataclass(frozen=True)
class RecordedEvent:
    check_id: str
    type: str
    data: Mapping[str, object]


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[RecordedEvent] = []
        self.live: list[RecordedEvent] = []

    async def emit(self, check_id: str, type: str, data: Mapping[str, object]) -> int:
        self.events.append(RecordedEvent(check_id, type, data))
        return len(self.events)

    async def publish_live(self, check_id: str, type: str, data: Mapping[str, object]) -> None:
        self.live.append(RecordedEvent(check_id, type, data))


class ScriptedChatModel(BaseChatModel):
    """replies are answered in order, one per model call; received holds the messages of each call
    and tools the tools of the last bind_tools."""

    replies: list[AIMessage]
    received: list[list[BaseMessage]] = Field(default_factory=list)
    tools: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        self.tools = list(tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.received.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self.received.append(list(messages))
        reply = self.replies.pop(0)
        chunks = [AIMessageChunk(content=piece, id=reply.id) for piece in _fragments(reply.text)]
        chunks.append(
            AIMessageChunk(
                content="",
                id=reply.id,
                tool_call_chunks=[
                    tool_call_chunk(
                        name=call["name"], args=json.dumps(call["args"]), id=call["id"], index=index
                    )
                    for index, call in enumerate(reply.tool_calls)
                ],
            )
        )
        for chunk in chunks:
            yield ChatGenerationChunk(message=chunk)


def _fragments(text: str, size: int = 4) -> list[str]:
    return [text[start : start + size] for start in range(0, len(text), size)]
