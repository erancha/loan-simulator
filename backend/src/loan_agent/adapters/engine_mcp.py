"""LoanEngine over the loan engine's MCP tools, reached over HTTP with a bearer token.

- McpLoanEngine: typed calls that parse each tool's structured content, and model_tools() for
  the model, which gets MODEL_ENGINE_TOOLS only
- Parsing helpers that turn the engine's decimal strings and ISO dates into Decimal and date;
  market_series_of() parses a market_series result

Each call opens its own MCP session, so the adapter holds no connection between calls.
"""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.types import CallToolResult, TextContent

from loan_agent.domain.models import OptionFigures
from loan_agent.ports.engine import (
    Bounds,
    EngineError,
    MarketPoint,
    MarketSeries,
    OfferTerm,
    ProposedTerm,
    Simulation,
)

_SERVER = "engine"
# The loan-side tools. The ceiling, the term proposals and the searches for a term or a loan are
# called by the check tools, so the model never builds a profile, a ceiling or a term rule.
MODEL_ENGINE_TOOLS = frozenset({"simulate_loan", "suggest_tracks", "market_series"})


class McpLoanEngine:
    def __init__(self, url: str, token: str) -> None:
        """url: the engine's MCP endpoint, path included (e.g. http://engine:8020/mcp)."""
        self._client = MultiServerMCPClient(
            {
                _SERVER: {
                    "transport": "streamable_http",
                    "url": url,
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            }
        )

    async def model_tools(self) -> list[BaseTool]:
        """The engine's MODEL_ENGINE_TOOLS for the model. Each tool message carries the engine's
        text as its content (a summary for simulate_loan, the result's JSON for the others) and
        the structured content, schedules included, as its artifact under the key
        structured_content."""
        tools = await self._client.get_tools(server_name=_SERVER)
        return [tool for tool in tools if tool.name in MODEL_ENGINE_TOOLS]

    async def assess(self, profile: Mapping[str, object]) -> Bounds:
        result = await self._call("assess_affordability", {"profile": dict(profile)})
        return Bounds(
            payment_ceiling=_money(result, "payment_ceiling"),
            reasons=tuple(result["reasons"]),
        )

    async def simulate(self, loan: Mapping[str, object]) -> Simulation:
        result = await self._call("simulate_loan", {"loan": dict(loan)})
        return Simulation(figures=_figures(result), structured=result)

    async def suggest(self, principal: Decimal, term_months: int) -> list[Mapping[str, object]]:
        result = await self._call(
            "suggest_tracks", {"principal": str(principal), "term_months": term_months}
        )
        tracks: list[Mapping[str, object]] = result["tracks"]
        return tracks

    async def offer_term(self, track: Mapping[str, object], payment_ceiling: Decimal) -> OfferTerm:
        result = await self._call(
            "shortest_comfortable_offer_term",
            {"track": dict(track), "payment_ceiling": str(payment_ceiling)},
        )
        return OfferTerm(term_months=result["term_months"], comfortable=result["comfortable"])

    async def propose_term(self, principal: Decimal, payment_limit: Decimal) -> ProposedTerm:
        result = await self._call(
            "propose_term", {"principal": str(principal), "payment_limit": str(payment_limit)}
        )
        return _proposed(result)

    async def propose_offer_term(
        self, track: Mapping[str, object], payment_limit: Decimal
    ) -> ProposedTerm:
        result = await self._call(
            "propose_offer_term", {"track": dict(track), "payment_limit": str(payment_limit)}
        )
        return _proposed(result)

    async def comfortable_term(
        self, principal: Decimal, payment_ceiling: Decimal, *, any_track: bool
    ) -> int | None:
        result = await self._call(
            "shortest_comfortable_term",
            {
                "principal": str(principal),
                "payment_ceiling": str(payment_ceiling),
                "any_track": any_track,
            },
        )
        term: int | None = result["term_months"]
        return term

    async def largest_loan(self, payment_ceiling: Decimal, term_months: int) -> Decimal | None:
        result = await self._call(
            "largest_comfortable_loan",
            {"payment_ceiling": str(payment_ceiling), "term_months": term_months},
        )
        return _optional_money(result, "loan_amount")

    async def market_series(self, months: int) -> MarketSeries:
        result = await self._call("market_series", {"prime_months": months, "cpi_months": months})
        return market_series_of(result)

    async def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self._client.session(_SERVER) as session:
            result = await session.call_tool(tool, arguments)
        if result.isError:
            raise EngineError(_text(result))
        if result.structuredContent is None:
            raise ValueError(f"The engine's {tool} returned no structured content")
        return result.structuredContent


def _proposed(result: Mapping[str, Any]) -> ProposedTerm:
    return ProposedTerm(
        term_months=result["term_months"], first_payment=_money(result, "first_payment")
    )


def _text(result: CallToolResult) -> str:
    (block,) = result.content
    if not isinstance(block, TextContent):
        raise TypeError(f"Expected a text block from the engine, got {block.type}")
    return block.text


def market_series_of(result: Mapping[str, Any]) -> MarketSeries:
    """The engine's market_series result, parsed."""
    return MarketSeries(
        prime=tuple(_point(row, "prime") for row in result["prime"]),
        rate_as_of=date.fromisoformat(result["rate_as_of"]),
        cpi_change=tuple(_point(row, "change_percent") for row in result["cpi"]),
        cpi_as_of=date.fromisoformat(result["cpi_as_of"]),
    )


def _point(row: Mapping[str, Any], key: str) -> MarketPoint:
    return MarketPoint(month=date.fromisoformat(row["month"]), value=_money(row, key))


def _money(data: Mapping[str, Any], key: str) -> Decimal:
    value = data[key]
    if not isinstance(value, str):
        raise TypeError(f"The engine sent {key} as {value!r}, not a decimal string")
    return Decimal(value)


def _optional_money(data: Mapping[str, Any], key: str) -> Decimal | None:
    return None if data[key] is None else _money(data, key)


def _figures(simulation: Mapping[str, Any]) -> OptionFigures:
    """The loan's totals with its single track's worst window and balloon."""
    tracks = simulation["tracks"]
    if len(tracks) != 1:
        raise EngineError("multi-track loans are not supported in phase 1")
    (track,) = tracks
    worst = track["worst"]
    return OptionFigures(
        first_payment=_money(simulation, "first_payment"),
        peak_payment=_money(simulation, "max_base_payment"),
        worst_peak_payment=None if worst is None else _money(worst, "max_payment"),
        worst_start=None if worst is None else date.fromisoformat(worst["start"]),
        worst_end=None if worst is None else date.fromisoformat(worst["end"]),
        balloon_due=_optional_money(track, "balloon_due"),
        total_paid=_money(simulation, "total_paid"),
        rate_as_of=date.fromisoformat(simulation["rate_as_of"]),
        cpi_as_of=date.fromisoformat(simulation["cpi_as_of"]),
    )
