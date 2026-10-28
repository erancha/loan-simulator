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
from mcp.types import CallToolResult, TextContent
from pydantic import Field
from starlette.types import ASGIApp, Receive, Scope, Send

from fakes import ENGINE_TOOL_NAMES
from loan_agent.adapters.engine_mcp import McpLoanEngine
from loan_agent.ports.engine import Bounds, EngineError, Sizing

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
    def size_loan(
        goal_price: str, trade_in_value: str, savings: str, min_cushion: str
    ) -> CallToolResult:
        arguments = {
            "goal_price": goal_price,
            "trade_in_value": trade_in_value,
            "savings": savings,
            "min_cushion": min_cushion,
        }
        calls.append(("size_loan", arguments))
        sizing = _fixture("size_loan")
        return _result(sizing, json.dumps(sizing))

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


async def test_assess_parses_bounds(engine: McpLoanEngine, stub: StubEngine) -> None:
    profile = {
        "net_fixed_income": "18000",
        "variable_income": "4000",
        "variable_income_stable": True,
        "fixed_expenses": "9000",
        "existing_loan_payments": "800",
    }

    bounds = await engine.assess(profile)

    assert bounds == Bounds(
        payment_ceiling=Decimal("4700.00"),
        min_cushion=Decimal("18000.00"),
        reasons=(
            "variable_income_half_counted",
            "ceiling_by_disposable_income",
            "existing_loans_deducted",
        ),
    )
    assert stub.calls == [("assess_affordability", {"profile": profile})]


async def test_size_sends_decimal_strings_and_parses_sizing(
    engine: McpLoanEngine, stub: StubEngine
) -> None:
    sizing = await engine.size(
        goal_price=Decimal(160000),
        trade_in_value=Decimal(40000),
        savings=Decimal(70000),
        min_cushion=Decimal("30000.00"),
    )

    assert sizing == Sizing(
        loan_amount=Decimal("80000.00"),
        savings_used=Decimal("40000.00"),
        cushion_kept=Decimal("30000.00"),
        spare_savings=Decimal("0.00"),
    )
    assert stub.calls == [
        (
            "size_loan",
            {
                "goal_price": "160000",
                "trade_in_value": "40000",
                "savings": "70000",
                "min_cushion": "30000.00",
            },
        )
    ]


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
    assert simulation.structured == _fixture("simulate_loan_unlinked_prime")


async def test_balloon_due_parsed(engine: McpLoanEngine) -> None:
    simulation = await engine.simulate({"tracks": [BALLOON_TRACK]})

    assert simulation.figures.balloon_due == Decimal("32472.96")
    assert simulation.figures.peak_payment == Decimal("1376.53")
    assert simulation.figures.worst_peak_payment == Decimal("1482.61")


async def test_multi_track_loan_raises_engine_error(engine: McpLoanEngine) -> None:
    with pytest.raises(EngineError, match="multi-track loans are not supported in phase 1"):
        await engine.simulate({"tracks": [PRIME_TRACK, PRIME_TRACK]})


async def test_suggest_returns_engine_tracks(engine: McpLoanEngine, stub: StubEngine) -> None:
    tracks = await engine.suggest(Decimal(80000), 48)

    assert tracks == _fixture("suggest_tracks")["tracks"]
    assert stub.calls == [("suggest_tracks", {"principal": "80000", "term_months": 48})]


async def test_tool_error_raises_engine_error_with_message(engine: McpLoanEngine) -> None:
    with pytest.raises(EngineError) as raised:
        await engine.suggest(Decimal(10), 48)

    message = str(raised.value)
    assert message.startswith("Error executing tool suggest_tracks:")
    assert "principal" in message
    assert "greater than or equal to 10000" in message


async def test_model_tools_keep_schedule_in_artifact(engine: McpLoanEngine) -> None:
    tools = {tool.name: tool for tool in await engine.model_tools()}

    assert set(tools) == ENGINE_TOOL_NAMES
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
