"""McpLoanEngine calls the engine's tools over HTTP and parses their structured results.

The engine here is a stub MCP server on a free localhost port whose tools carry the engine's names
and answer with results captured from the real engine (fixtures/engine).
"""

import asyncio
import json
import socket
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import pytest
import uvicorn
from langchain_core.messages import ToolMessage
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import Field
from starlette.types import ASGIApp, Receive, Scope, Send

from loan_agent.adapters.engine_mcp import MODEL_ENGINE_TOOLS, McpLoanEngine
from loan_agent.domain.models import OptionPrice
from loan_agent.ports.engine import (
    Bounds,
    EngineError,
    MarketPoint,
    OfferTerm,
    ProposedTerm,
)

FIXTURES = Path(__file__).parent / "fixtures" / "engine"
TOKEN = "0123456789abcdef" * 3
PRIME_TRACK = {
    "principal": "80000",
    "term_months": 48,
    "rate_kind": "prime",
    "prime_spread": "1.5",
    "cpi_linked": False,
    "method": "spitzer",
}
BALLOON_TRACK = {
    "principal": "80000",
    "term_months": 48,
    "rate_kind": "fixed",
    "annual_rate": "4.9",
    "cpi_linked": True,
    "method": "balloon",
    "balloon_amount": "30000",
}


def _fixture(name: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return result


def _result(structured: dict[str, Any], text: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)], structuredContent=structured
    )


@dataclass
class StubEngine:
    url: str
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


def _stub_server(calls: list[tuple[str, dict[str, Any]]]) -> FastMCP:
    server = FastMCP("loan-engine-stub", stateless_http=True)

    @server.tool()
    def assess_affordability(profile: dict[str, Any]) -> CallToolResult:
        calls.append(("assess_affordability", {"profile": profile}))
        bounds = _fixture("assess_affordability")
        return _result(bounds, json.dumps(bounds))

    @server.tool()
    def simulate_loan(loan: dict[str, Any]) -> CallToolResult:
        calls.append(("simulate_loan", {"loan": loan}))
        tracks = loan["tracks"]
        name = "linked_balloon" if tracks[0]["method"] == "balloon" else "unlinked_prime"
        simulation = _fixture(f"simulate_loan_{name}")
        simulation["tracks"] = simulation["tracks"] * len(tracks)
        summary = (
            f"Loan: first payment {simulation['first_payment']} ₪; peak recurring payment "
            f"{simulation['max_base_payment']} ₪; total repaid {simulation['total_paid']} ₪. "
            "The month-by-month schedule is in the structured content."
        )
        return _result(simulation, summary)

    @server.tool()
    def suggest_tracks(
        principal: Annotated[Decimal, Field(ge=10000, le=500000)], term_months: int
    ) -> CallToolResult:
        calls.append(("suggest_tracks", {"principal": str(principal), "term_months": term_months}))
        suggestions = _fixture("suggest_tracks")
        return _result(suggestions, json.dumps(suggestions))

    @server.tool()
    def shortest_comfortable_term(
        principal: str, payment_ceiling: str, any_track: bool = False
    ) -> CallToolResult:
        arguments = {
            "principal": principal,
            "payment_ceiling": payment_ceiling,
            "any_track": any_track,
        }
        calls.append(("shortest_comfortable_term", arguments))
        if Decimal(principal) < 20000:
            raise ToolError("the market data is unavailable")
        term = {"term_months": None if Decimal(principal) > 100000 else 24}
        return _result(term, json.dumps(term))

    @server.tool()
    def shortest_comfortable_offer_term(
        track: dict[str, Any], payment_ceiling: str
    ) -> CallToolResult:
        calls.append(
            (
                "shortest_comfortable_offer_term",
                {"track": track, "payment_ceiling": payment_ceiling},
            )
        )
        term = {"term_months": 24, "comfortable": True}
        return _result(term, json.dumps(term))

    @server.tool()
    def propose_term(principal: str, payment_limit: str) -> CallToolResult:
        calls.append(("propose_term", {"principal": principal, "payment_limit": payment_limit}))
        term = {"term_months": 30, "first_payment": "1750.50"}
        return _result(term, json.dumps(term))

    @server.tool()
    def propose_offer_term(track: dict[str, Any], payment_limit: str) -> CallToolResult:
        calls.append(("propose_offer_term", {"track": track, "payment_limit": payment_limit}))
        term = {"term_months": 36, "first_payment": "1500.00"}
        return _result(term, json.dumps(term))

    @server.tool()
    def largest_comfortable_loan(payment_ceiling: str, term_months: int) -> CallToolResult:
        calls.append(
            (
                "largest_comfortable_loan",
                {"payment_ceiling": payment_ceiling, "term_months": term_months},
            )
        )
        largest = {"loan_amount": None if term_months < 12 else "90000.00"}
        return _result(largest, json.dumps(largest))

    @server.tool()
    def offer_readings(
        principal: str,
        term_months: int,
        stated_rate: str | None = None,
        monthly_payment: str | None = None,
        prime_total: bool = False,
    ) -> CallToolResult:
        arguments = {
            "principal": principal,
            "term_months": term_months,
            "stated_rate": stated_rate,
            "monthly_payment": monthly_payment,
            "prime_total": prime_total,
        }
        calls.append(("offer_readings", arguments))
        if stated_rate is None and monthly_payment is None:
            raise ToolError("an offer needs a stated rate or a monthly payment")
        readings = _fixture("offer_readings")
        return _result(readings, json.dumps(readings))

    @server.tool()
    def market_series(prime_months: int, cpi_months: int) -> CallToolResult:
        calls.append(("market_series", {"prime_months": prime_months, "cpi_months": cpi_months}))
        series = _fixture("market_series")
        return _result(series, json.dumps(series))

    return server


class _BearerGate:
    """Answers 401 to any HTTP request without the engine's bearer token, as the engine does."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            if headers.get(b"authorization") != f"Bearer {TOKEN}".encode():
                await send({"type": "http.response.start", "status": 401, "headers": []})
                await send({"type": "http.response.body", "body": b""})
                return
        await self.app(scope, receive, send)


@pytest.fixture
async def stub() -> AsyncIterator[StubEngine]:
    calls: list[tuple[str, dict[str, Any]]] = []
    app = _BearerGate(_stub_server(calls).streamable_http_app())
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    while not server.started:
        if serving.done():
            serving.result()
            raise RuntimeError("The stub engine stopped before it started serving")
        await asyncio.sleep(0.01)
    yield StubEngine(url=f"http://127.0.0.1:{port}/mcp", calls=calls)
    server.should_exit = True
    await serving


@pytest.fixture
def engine(stub: StubEngine) -> McpLoanEngine:
    return McpLoanEngine(stub.url, TOKEN)


async def test_offer_term_sends_the_track_and_parses_the_term(
    engine: McpLoanEngine, stub: StubEngine
) -> None:
    track = {"principal": "32000", "term_months": 84}

    term = await engine.offer_term(track, Decimal(2000))

    assert term == OfferTerm(term_months=24, comfortable=True)
    assert stub.calls == [
        ("shortest_comfortable_offer_term", {"track": track, "payment_ceiling": "2000"})
    ]


async def test_assess_parses_bounds(engine: McpLoanEngine, stub: StubEngine) -> None:
    profile = {
        "net_fixed_income": "18000",
        "variable_income": "4000",
        "variable_income_minimum": "2000",
        "fixed_expenses": "9000",
        "existing_loan_payments": "800",
    }

    bounds = await engine.assess(profile)

    assert bounds == Bounds(
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
    assert stub.calls == [("assess_affordability", {"profile": profile})]


async def test_propose_term_parses_term_and_first_payment(
    engine: McpLoanEngine, stub: StubEngine
) -> None:
    proposed = await engine.propose_term(Decimal(80000), Decimal("1800.00"))
    offered = await engine.propose_offer_term({"principal": "32000"}, Decimal(1600))

    assert proposed == ProposedTerm(term_months=30, first_payment=Decimal("1750.50"))
    assert offered == ProposedTerm(term_months=36, first_payment=Decimal("1500.00"))
    assert stub.calls == [
        ("propose_term", {"principal": "80000", "payment_limit": "1800.00"}),
        ("propose_offer_term", {"track": {"principal": "32000"}, "payment_limit": "1600"}),
    ]


async def test_comfortable_term_parses_the_term(engine: McpLoanEngine, stub: StubEngine) -> None:
    term = await engine.comfortable_term(Decimal(80000), Decimal(2000), any_track=True)

    assert term == 24
    assert stub.calls == [
        (
            "shortest_comfortable_term",
            {"principal": "80000", "payment_ceiling": "2000", "any_track": True},
        )
    ]


async def test_comfortable_term_is_none_when_no_term_fits(engine: McpLoanEngine) -> None:
    assert await engine.comfortable_term(Decimal(200000), Decimal(900), any_track=False) is None


async def test_comfortable_term_raises_other_engine_errors(engine: McpLoanEngine) -> None:
    with pytest.raises(EngineError, match="market data is unavailable"):
        await engine.comfortable_term(Decimal(10000), Decimal(900), any_track=False)


async def test_largest_loan_parses_the_amount_or_none(
    engine: McpLoanEngine, stub: StubEngine
) -> None:
    assert await engine.largest_loan(Decimal(2000), 60) == Decimal("90000.00")
    assert await engine.largest_loan(Decimal(100), 6) is None
    assert stub.calls[0] == (
        "largest_comfortable_loan",
        {"payment_ceiling": "2000", "term_months": 60},
    )


async def test_simulate_parses_figures_and_keeps_structured(engine: McpLoanEngine) -> None:
    simulation = await engine.simulate({"tracks": [PRIME_TRACK]})

    figures = simulation.figures
    assert figures.first_payment == Decimal("1887.99")
    assert figures.peak_payment == Decimal("1887.99")
    assert figures.total_paid == Decimal("90623.31")
    assert figures.worst_peak_payment == Decimal("2038.63")
    assert figures.worst_start == date(2022, 4, 1)
    assert figures.worst_end == date(2026, 3, 1)
    assert figures.balloon_due is None
    assert figures.rate_as_of == date(2026, 10, 26)
    assert figures.cpi_as_of == date(2026, 9, 1)
    assert figures.price == OptionPrice(
        rate_today=Decimal("6.25"),
        against_market="below",
        market_rate=Decimal("7.9"),
        market_rate_month=date(2026, 8, 1),
    )
    assert simulation.structured == _fixture("simulate_loan_unlinked_prime")


async def test_balloon_due_parsed(engine: McpLoanEngine) -> None:
    simulation = await engine.simulate({"tracks": [BALLOON_TRACK]})

    assert simulation.figures.balloon_due == Decimal("32472.96")
    assert simulation.figures.price is not None
    assert simulation.figures.price.rate_today == Decimal("4.9")
    assert simulation.figures.price.against_market is None
    assert simulation.figures.peak_payment == Decimal("1376.53")
    assert simulation.figures.worst_peak_payment == Decimal("1482.61")


async def test_multi_track_loan_raises_engine_error(engine: McpLoanEngine) -> None:
    with pytest.raises(EngineError, match="multi-track loans are not supported in phase 1"):
        await engine.simulate({"tracks": [PRIME_TRACK, PRIME_TRACK]})


async def test_suggest_returns_engine_tracks(engine: McpLoanEngine, stub: StubEngine) -> None:
    tracks = await engine.suggest(Decimal(80000), 48)

    assert tracks == _fixture("suggest_tracks")["tracks"]
    assert stub.calls == [("suggest_tracks", {"principal": "80000", "term_months": 48})]


async def test_market_series_parses_both_series(engine: McpLoanEngine, stub: StubEngine) -> None:
    market = await engine.market_series(60)

    assert stub.calls == [("market_series", {"prime_months": 60, "cpi_months": 60})]
    assert (len(market.prime), len(market.cpi_change)) == (60, 12)
    assert market.prime[-1] == MarketPoint(date(2026, 10, 1), Decimal("4.75"))
    assert market.cpi_change[-1] == MarketPoint(date(2026, 9, 1), Decimal("-0.5"))
    assert (market.rate_as_of, market.cpi_as_of) == (date(2026, 10, 30), date(2026, 9, 1))


async def test_offer_readings_sends_the_offer_and_parses_its_readings(
    engine: McpLoanEngine, stub: StubEngine
) -> None:
    offer = await engine.offer_readings(Decimal(45000), 60, None, Decimal(969), prime_total=False)

    assert stub.calls == [
        (
            "offer_readings",
            {
                "principal": "45000",
                "term_months": 60,
                "stated_rate": None,
                "monthly_payment": "969",
                "prime_total": False,
            },
        )
    ]
    assert (offer.prime, offer.rate_as_of, offer.payment_rate) == (
        Decimal("4.75"),
        date(2026, 10, 20),
        Decimal("10.58"),
    )
    assert [reading.kind for reading in offer.readings] == [
        "fixed_unlinked",
        "prime_margin",
        "fixed_linked",
    ]
    linked = offer.readings[2]
    assert linked.approximate is True
    assert linked.first_payment == Decimal("970.61")
    assert linked.track == _fixture("offer_readings")["readings"][2]["track"]


async def test_offer_readings_raises_engine_error(engine: McpLoanEngine) -> None:
    with pytest.raises(EngineError, match="a stated rate or a monthly payment"):
        await engine.offer_readings(Decimal(45000), 60, None, None, prime_total=False)


async def test_tool_error_raises_engine_error_with_message(engine: McpLoanEngine) -> None:
    with pytest.raises(EngineError) as raised:
        await engine.suggest(Decimal(10), 48)

    message = str(raised.value)
    assert message.startswith("Error executing tool suggest_tracks:")
    assert "principal" in message
    assert "greater than or equal to 10000" in message


async def test_model_tools_are_the_loan_side_allow_list(engine: McpLoanEngine) -> None:
    tools = await engine.model_tools()

    assert {tool.name for tool in tools} == MODEL_ENGINE_TOOLS
    assert MODEL_ENGINE_TOOLS == {"simulate_loan", "market_series"}


async def test_model_tools_keep_schedule_in_artifact(engine: McpLoanEngine) -> None:
    tools = {tool.name: tool for tool in await engine.model_tools()}

    assert set(tools) == MODEL_ENGINE_TOOLS
    assert {tool.response_format for tool in tools.values()} == {"content_and_artifact"}
    message = await tools["simulate_loan"].ainvoke(
        {
            "type": "tool_call",
            "id": "call-1",
            "name": "simulate_loan",
            "args": {"loan": {"tracks": [PRIME_TRACK]}},
        }
    )

    assert isinstance(message, ToolMessage)
    content = json.dumps(message.content)
    assert "1887.99" in content
    assert "balance" not in content
    artifact: Mapping[str, Any] = message.artifact
    assert len(artifact["structured_content"]["tracks"][0]["schedule"]) == 48
