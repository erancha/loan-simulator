"""In-memory test doubles for the application's ports.

Core building blocks:
- InMemoryCheckRepository, InMemoryOptionRepository,
  InMemoryRecommendationRepository: dict-backed storage
- FakeLoanEngine: answers with values captured from the real engine (adapters/fixtures/engine),
  overridable per test, and records its calls
- InMemoryCheckEventStore: the per-check event log, stamped by the given clock
- RecordingSink: records stored and live events
- ScriptedChatModel: a chat model that answers with predefined messages in order, streaming each
  one's text in fragments followed by its tool calls, and records what it was given
"""

import json
from collections.abc import AsyncIterator, Callable, Collection, Mapping
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

from loan_agent.adapters.engine_mcp import market_series_of
from loan_agent.domain.errors import CheckNotFoundError
from loan_agent.domain.models import (
    CeilingSource,
    Check,
    Finances,
    LoanRequest,
    Option,
    OptionFigures,
    Recommendation,
)
from loan_agent.ports.engine import (
    Bounds,
    EngineError,
    MarketSeries,
    OfferTerm,
    ProposedTerm,
    Simulation,
)
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
ENGINE_TOOL_NAMES = {
    "assess_affordability",
    "simulate_loan",
    "shortest_comfortable_term",
    "shortest_comfortable_offer_term",
    "propose_term",
    "propose_offer_term",
    "largest_comfortable_loan",
    "suggest_tracks",
    "market_series",
}
COMFORTABLE_OFFER_TERM = OfferTerm(term_months=24, comfortable=True)
PROPOSED_TERM = ProposedTerm(term_months=24, first_payment=Decimal("1750.00"))
ENGINE_FIXTURES = Path(__file__).parent / "adapters" / "fixtures" / "engine"
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


def engine_fixture(name: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((ENGINE_FIXTURES / f"{name}.json").read_text())
    return result


ASSESSED_BOUNDS = Bounds(
    payment_ceiling=Decimal("4700.00"),
    income_share=Decimal("0.30"),
    ceiling_by_income_share=Decimal("6000.00"),
    disposable_share=Decimal("0.50"),
    ceiling_by_disposable_income=Decimal("4700.00"),
    reasons=(
        "variable_income_minimum_counted",
        "ceiling_by_disposable_income",
        "existing_loans_deducted",
    ),
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


class InMemoryCheckRepository:
    """clone copies options and the recommendation only when option_store and
    recommendation_store are set."""

    def __init__(self) -> None:
        self.rows: dict[str, Check] = {}
        self.event_store: InMemoryCheckEventStore | None = None
        self.option_store: InMemoryOptionRepository | None = None
        self.recommendation_store: InMemoryRecommendationRepository | None = None

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

    async def delete(self, check_id: str, kept_type: str, kept_since: datetime) -> None:
        """Options and recommendations stay in their fakes, where nothing reaches them without
        the check; the Postgres tests prove they go."""
        check = self.rows.pop(check_id)
        assert self.event_store is not None
        self.event_store.forget(check, kept_type, kept_since)

    async def set_loan(self, check_id: str, loan: LoanRequest) -> None:
        self.rows[check_id] = replace(self.rows[check_id], loan=loan)

    async def set_term(self, check_id: str, term_months: int) -> None:
        self.rows[check_id] = replace(self.rows[check_id], term_months=term_months)

    async def set_ceiling(self, check_id: str, ceiling: Decimal, source: CeilingSource) -> None:
        self.rows[check_id] = replace(
            self.rows[check_id], payment_ceiling=ceiling, ceiling_source=source
        )

    async def set_finances(self, check_id: str, finances: Finances) -> None:
        self.rows[check_id] = replace(self.rows[check_id], finances=finances)

    async def latest_finances(self, user_id: str, other_than: str) -> Finances | None:
        others = [
            check
            for check in await self.list(user_id)
            if check.id != other_than and not check.finances.missing()
        ]
        return others[0].finances if others else None

    async def archive(self, check_id: str, at: datetime) -> None:
        if check_id not in self.rows:
            raise CheckNotFoundError(check_id)
        self.rows[check_id] = replace(self.rows[check_id], archived_at=at)

    async def restore(self, check_id: str) -> None:
        self.rows[check_id] = replace(self.rows[check_id], archived_at=None)

    async def clone(self, source_id: str, clone: Check, left_out: Collection[str]) -> None:
        self.rows[clone.id] = clone
        if self.option_store is not None:
            self.option_store.rows[clone.id] = [
                replace(option, check_id=clone.id)
                for option in self.option_store.rows.get(source_id, [])
            ]
        if self.recommendation_store is not None:
            recommendation = self.recommendation_store.rows.get(source_id)
            if recommendation is not None:
                self.recommendation_store.rows[clone.id] = replace(
                    recommendation, check_id=clone.id
                )
        assert self.event_store is not None
        self.event_store.copy(source_id, clone.id, left_out)


class InMemoryOptionRepository:
    def __init__(self) -> None:
        self.rows: dict[str, list[Option]] = {}

    async def add(self, option: Option) -> None:
        self.rows.setdefault(option.check_id, []).append(option)

    async def replace(self, option: Option) -> None:
        options = self.rows[option.check_id]
        (index,) = [i for i, kept in enumerate(options) if kept.id == option.id]
        options[index] = option

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
        checks.event_store = self
        # Key: person and event type. Value: the kept times of a deleted check's events.
        self._kept: dict[tuple[str, str], list[datetime]] = {}
        # Key: id of a check cloned from another. Value: how many of its first events are copies.
        self._copied: dict[str, int] = {}

    def copy(self, source_id: str, target_id: str, left_out: Collection[str]) -> None:
        kept = [event for event in self.rows.get(source_id, []) if event.type not in left_out]
        self.rows[target_id] = [replace(event, seq=seq) for seq, event in enumerate(kept, 1)]
        self._copied[target_id] = len(kept)

    async def append(self, check_id: str, type: str, data: Mapping[str, object]) -> StoredEvent:
        if check_id not in self._checks.rows:
            raise CheckNotFoundError(check_id)
        log = self.rows.setdefault(check_id, [])
        log.append(StoredEvent(len(log) + 1, type, data, self._clock()))
        return log[-1]

    async def list(self, check_id: str, after_seq: int) -> list[StoredEvent]:
        return [event for event in self.rows.get(check_id, []) if event.seq > after_seq]

    async def count_since(self, user_id: str, type: str, since: datetime) -> tuple[int, EventTimes]:
        times = sorted(
            event.created_at
            for check_id, log in self.rows.items()
            if self._checks.rows[check_id].user_id == user_id
            for event in log
            if event.type == type
            and event.created_at > since
            and event.seq > self._copied.get(check_id, 0)
        )
        kept = [time for time in self._kept.get((user_id, type), []) if time > since]
        times = sorted(times + kept)
        return len(times), times

    def forget(self, check: Check, kept_type: str, kept_since: datetime) -> None:
        copied = self._copied.pop(check.id, 0)
        self._kept[(check.user_id, kept_type)] = [
            *self._kept.get((check.user_id, kept_type), []),
            *(
                event.created_at
                for event in self.rows.pop(check.id, [])
                if event.type == kept_type and event.created_at > kept_since and event.seq > copied
            ),
        ]

    async def checks_with(self, user_id: str, type: str) -> CheckIds:
        return sorted(
            check_id
            for check_id, log in self.rows.items()
            if self._checks.rows[check_id].user_id == user_id
            and any(event.type == type for event in log)
        )

    async def checks_whose_latest(self, type: str, data: Mapping[str, object]) -> CheckIds:
        latest = {}
        for check_id, log in self.rows.items():
            of_type = [event for event in log if event.type == type]
            if of_type:
                latest[check_id] = of_type[-1].data
        return sorted(check_id for check_id, found in latest.items() if found == data)


@dataclass
class FakeLoanEngine:
    """simulations are answered in order; simulate_error, suggest_error, assess_error and
    market_error, when set, are raised instead; suggest answers the captured tracks at the
    principal and term asked for; market_series answers from the captured engine result.
    comfortable_terms and largest_loans answer the ceiling searches, None meaning nothing fits."""

    bounds: Bounds = ASSESSED_BOUNDS
    simulations: list[Simulation] = field(default_factory=list)
    simulate_error: EngineError | None = None
    suggest_error: EngineError | None = None
    assess_error: EngineError | None = None
    market_error: EngineError | None = None
    offer_terms: OfferTerm = COMFORTABLE_OFFER_TERM
    offer_term_error: EngineError | None = None
    proposed: ProposedTerm = PROPOSED_TERM
    comfortable_terms: int | None = 24
    largest_loans: Decimal | None = Decimal("90000.00")
    calls: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    async def assess(self, profile: Mapping[str, object]) -> Bounds:
        self.calls.append(("assess", profile))
        if self.assess_error is not None:
            raise self.assess_error
        return self.bounds

    async def simulate(self, loan: Mapping[str, object]) -> Simulation:
        self.calls.append(("simulate", loan))
        if self.simulate_error is not None:
            raise self.simulate_error
        return self.simulations.pop(0)

    async def suggest(self, principal: Decimal, term_months: int) -> list[Mapping[str, object]]:
        self.calls.append(("suggest", {"principal": principal, "term_months": term_months}))
        if self.suggest_error is not None:
            raise self.suggest_error
        tracks: list[Mapping[str, object]] = engine_fixture("suggest_tracks")["tracks"]
        return [
            {**track, "principal": str(principal), "term_months": term_months} for track in tracks
        ]

    async def offer_term(self, track: Mapping[str, object], payment_ceiling: Decimal) -> OfferTerm:
        self.calls.append(("offer_term", {"track": track, "payment_ceiling": payment_ceiling}))
        if self.offer_term_error is not None:
            raise self.offer_term_error
        return self.offer_terms

    async def propose_term(self, principal: Decimal, payment_limit: Decimal) -> ProposedTerm:
        self.calls.append(
            ("propose_term", {"principal": principal, "payment_limit": payment_limit})
        )
        return self.proposed

    async def propose_offer_term(
        self, track: Mapping[str, object], payment_limit: Decimal
    ) -> ProposedTerm:
        self.calls.append(("propose_offer_term", {"track": track, "payment_limit": payment_limit}))
        return self.proposed

    async def comfortable_term(
        self, principal: Decimal, payment_ceiling: Decimal, *, any_track: bool
    ) -> int | None:
        self.calls.append(
            (
                "comfortable_term",
                {
                    "principal": principal,
                    "payment_ceiling": payment_ceiling,
                    "any_track": any_track,
                },
            )
        )
        return self.comfortable_terms

    async def largest_loan(self, payment_ceiling: Decimal, term_months: int) -> Decimal | None:
        self.calls.append(
            ("largest_loan", {"payment_ceiling": payment_ceiling, "term_months": term_months})
        )
        return self.largest_loans

    async def market_series(self, months: int) -> MarketSeries:
        self.calls.append(("market_series", {"months": months}))
        if self.market_error is not None:
            raise self.market_error
        return market_series_of(engine_fixture("market_series"))


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

    async def latest(self, check_id: str, type: str) -> Mapping[str, object] | None:
        of_type = [e for e in self.events if e.check_id == check_id and e.type == type]
        return of_type[-1].data if of_type else None


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
