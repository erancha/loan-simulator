import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from mcp import Client

from loan_engine.domain.history import MarketHistory, simulate
from loan_engine.domain.models import Track
from loan_engine.service.config import Settings
from loan_engine.service.server import build_server

TOOLS = {
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
RESOURCES = {"rates://boi/history", "rates://cpi/history", "rates://current"}

PRIME_TRACK: dict[str, Any] = {
    "principal": 31000,
    "term_months": 48,
    "rate_kind": "prime",
    "prime_spread": "2.9",
    "cpi_linked": False,
    "method": "spitzer",
}


def cents(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def client(settings: Settings, history: MarketHistory) -> Client:
    return Client(build_server(settings, lambda: history))


async def test_lists_tools_and_resources(settings: Settings, history: MarketHistory) -> None:
    async with client(settings, history) as c:
        tools = (await c.list_tools()).tools
        resources = (await c.list_resources()).resources
    assert {tool.name for tool in tools} == TOOLS
    for tool in tools:
        assert tool.description and tool.output_schema, tool.name
    assert {str(resource.uri) for resource in resources} == RESOURCES


async def test_assess_affordability_reference_user(
    settings: Settings, history: MarketHistory
) -> None:
    profile = {
        "net_fixed_income": 8600,
        "fixed_expenses": 5500,
    }
    async with client(settings, history) as c:
        result = await c.call_tool("assess_affordability", {"profile": profile})
    assert not result.is_error, result.content
    assert result.structured_content == {
        "payment_ceiling": "1550.00",
        "counted_income": "8600.00",
        "reasons": ["ceiling_by_disposable_income"],
    }


async def test_simulate_loan_returns_summary_schedule_and_data_dates(
    settings: Settings, history: MarketHistory
) -> None:
    fixed = {
        "principal": 20000,
        "term_months": 24,
        "rate_kind": "fixed",
        "annual_rate": "7.9",
        "cpi_linked": False,
        "method": "spitzer",
        "one_time_fee": 300,
    }
    async with client(settings, history) as c:
        result = await c.call_tool("simulate_loan", {"loan": {"tracks": [PRIME_TRACK, fixed]}})
    assert not result.is_error, result.content
    loan = result.structured_content
    assert loan is not None

    prime_outcome = simulate(Track.model_validate(PRIME_TRACK), history)
    fixed_outcome = simulate(Track.model_validate(fixed), history)
    prime, fixed_sim = loan["tracks"]
    assert prime["first_payment"] == cents(prime_outcome.base.first_payment)
    assert prime["total_paid"] == cents(prime_outcome.base.total_paid)
    assert prime["windows"] == 120 - 48 + 1
    assert prime_outcome.worst is not None and prime_outcome.max_payment_range is not None
    assert prime["worst"] == {
        "start": prime_outcome.worst.start.isoformat(),
        "end": prime_outcome.worst.end.isoformat(),
        "max_payment": cents(prime_outcome.worst.max_payment),
        "balloon_due": None,
        "total_paid": cents(prime_outcome.worst.total_paid),
    }
    assert prime["balloon_due"] is None
    assert prime["max_payment_range"] == {
        "low": cents(prime_outcome.max_payment_range[0]),
        "high": cents(prime_outcome.max_payment_range[1]),
    }
    assert len(prime["schedule"]) == 48
    first_row = prime_outcome.base.rows[0]
    assert prime["schedule"][0] == {
        "month": 1,
        "annual_rate": str(first_row.annual_rate),
        "payment": cents(first_row.payment),
        "interest": cents(first_row.interest),
        "principal": cents(first_row.principal),
        "balance": cents(first_row.balance),
    }
    assert fixed_sim["worst"] is None and fixed_sim["windows"] == 0

    prime_rows, fixed_rows = prime_outcome.base.rows, fixed_outcome.base.rows
    assert loan["first_payment"] == cents(prime_rows[0].payment + fixed_rows[0].payment)
    assert loan["max_base_payment"] == cents(
        max(prime_rows[m].payment + (fixed_rows[m].payment if m < 24 else 0) for m in range(48))
    )
    assert loan["total_paid"] == cents(
        prime_outcome.base.total_paid + fixed_outcome.base.total_paid
    )
    assert (loan["rate_as_of"], loan["cpi_as_of"]) == ("2026-10-20", "2026-09-01")


async def test_simulate_loan_reports_balloon_apart_from_peak_payment(
    settings: Settings, history: MarketHistory
) -> None:
    balloon = {**PRIME_TRACK, "cpi_linked": True, "method": "balloon", "balloon_amount": 15000}
    async with client(settings, history) as c:
        result = await c.call_tool("simulate_loan", {"loan": {"tracks": [balloon]}})
    assert not result.is_error, result.content
    loan = result.structured_content
    assert loan is not None

    outcome = simulate(Track.model_validate(balloon), history)
    assert outcome.base.balloon_due is not None and outcome.worst is not None
    assert outcome.worst.balloon_due is not None
    (track,) = loan["tracks"]
    assert track["max_base_payment"] == cents(outcome.base.max_payment)
    assert track["balloon_due"] == cents(outcome.base.balloon_due)
    assert track["worst"]["max_payment"] == cents(outcome.worst.max_payment)
    assert track["worst"]["balloon_due"] == cents(outcome.worst.balloon_due)
    assert loan["max_base_payment"] == cents(outcome.base.max_payment)
    assert Decimal(loan["max_base_payment"]) < Decimal(track["schedule"][-1]["payment"])


async def test_simulate_loan_text_is_a_summary_and_schedule_is_structured(
    settings: Settings, history: MarketHistory
) -> None:
    balloon = {**PRIME_TRACK, "method": "balloon", "balloon_amount": 15000}
    async with client(settings, history) as c:
        tools = {tool.name: tool for tool in (await c.list_tools()).tools}
        result = await c.call_tool("simulate_loan", {"loan": {"tracks": [PRIME_TRACK, balloon]}})
    assert not result.is_error, result.content
    output_schema = tools["simulate_loan"].output_schema
    assert output_schema is not None and "tracks" in output_schema["properties"]
    loan = result.structured_content
    assert loan is not None
    assert [len(track["schedule"]) for track in loan["tracks"]] == [48, 48]

    (block,) = result.content
    assert block.type == "text"
    text = block.text
    assert "{" not in text and '"schedule"' not in text
    second_row = loan["tracks"][0]["schedule"][1]
    assert second_row["interest"] not in text and second_row["balance"] not in text
    prime, balloon_sim = loan["tracks"]
    for value in (
        prime["first_payment"],
        prime["max_base_payment"],
        prime["total_paid"],
        prime["worst"]["start"][:7],
        prime["worst"]["end"][:7],
        prime["worst"]["max_payment"],
        balloon_sim["balloon_due"],
        balloon_sim["worst"]["balloon_due"],
        loan["first_payment"],
        loan["max_base_payment"],
        loan["total_paid"],
        loan["rate_as_of"],
        loan["cpi_as_of"][:7],
    ):
        assert value in text, value
    assert text.count("balloon") == 2


async def test_simulate_loan_without_history_window_is_tool_error(
    settings: Settings, short_history: MarketHistory
) -> None:
    async with client(settings, short_history) as c:
        result = await c.call_tool("simulate_loan", {"loan": {"tracks": [PRIME_TRACK]}})
    assert result.is_error
    assert "term of 48 months exceeds the 30 months of history" in result.content[0].text


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"method": "balloon", "balloon_amount": 31000}, "balloon_amount must be below principal"),
        ({"one_time_fee": -1}, "one_time_fee"),
        ({"term_months": 97}, "term_months"),
        (
            {"method": "equal_principal", "balloon_amount": 5000},
            "balloon_amount must be 0 unless method is 'balloon'",
        ),
        ({"method": "balloon"}, "balloon_amount must be above 0 when method is 'balloon'"),
        ({"rate_kind": "fixed", "prime_spread": None, "annual_rate": -1}, "annual_rate"),
        ({"prime_spread": 21}, "prime_spread"),
    ],
)
async def test_invalid_track_is_tool_error_naming_field(
    settings: Settings, history: MarketHistory, overrides: dict[str, Any], field: str
) -> None:
    async with client(settings, history) as c:
        result = await c.call_tool(
            "simulate_loan", {"loan": {"tracks": [{**PRIME_TRACK, **overrides}]}}
        )
    assert result.is_error
    assert field in result.content[0].text


async def test_suggest_tracks_names_source_and_month(
    settings: Settings, history: MarketHistory
) -> None:
    async with client(settings, history) as c:
        result = await c.call_tool("suggest_tracks", {"principal": 31000, "term_months": 48})
    assert not result.is_error, result.content
    suggestions = result.structured_content
    assert suggestions is not None
    assert suggestions["as_of"] == "2026-08-01"
    assert "BNK_99010_LR_BIR_1893" in suggestions["source"]
    fixed, prime = suggestions["tracks"]
    assert (fixed["rate_kind"], fixed["annual_rate"]) == ("fixed", "7.9")
    assert (prime["rate_kind"], prime["prime_spread"]) == ("prime", "2.9")


async def test_shortest_comfortable_term_names_the_term(
    settings: Settings, history: MarketHistory
) -> None:
    arguments = {"principal": 31000, "payment_ceiling": 1000}
    async with client(settings, history) as c:
        result = await c.call_tool("shortest_comfortable_term", arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["term_months"] % 6 == 0


async def test_shortest_comfortable_term_is_null_when_no_term_fits(
    settings: Settings, history: MarketHistory
) -> None:
    async with client(settings, history) as c:
        nothing_fits = await c.call_tool(
            "shortest_comfortable_term", {"principal": 31000, "payment_ceiling": 100}
        )
        too_large = await c.call_tool(
            "shortest_comfortable_term", {"principal": 500000, "payment_ceiling": 2000}
        )
    for result in (nothing_fits, too_large):
        assert not result.is_error, result.content
        assert result.structured_content == {"term_months": None}


async def test_offer_term_is_the_shortest_comfortable_term_under_the_maximum(
    settings: Settings, history: MarketHistory
) -> None:
    arguments = {"track": {**PRIME_TRACK, "term_months": 84}, "payment_ceiling": 2000}
    async with client(settings, history) as c:
        result = await c.call_tool("shortest_comfortable_offer_term", arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["comfortable"] is True
    assert result.structured_content["term_months"] < 84


async def test_offer_term_falls_back_to_the_maximum_when_no_term_is_comfortable(
    settings: Settings, history: MarketHistory
) -> None:
    arguments = {"track": {**PRIME_TRACK, "term_months": 84}, "payment_ceiling": 100}
    async with client(settings, history) as c:
        result = await c.call_tool("shortest_comfortable_offer_term", arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["comfortable"] is False
    assert result.structured_content["term_months"] == 84


async def test_market_series_returns_the_latest_months_ending_with_today_s_prime(
    settings: Settings, history: MarketHistory
) -> None:
    async with client(settings, history) as c:
        result = await c.call_tool("market_series", {"prime_months": 3, "cpi_months": 2})
    assert not result.is_error, result.content
    assert result.structured_content == {
        "current_prime": "4.75",
        "rate_as_of": "2026-10-20",
        "prime": [
            {"month": "2009-11-01", "prime": "6.25"},
            {"month": "2009-12-01", "prime": "6.375"},
            {"month": "2026-10-01", "prime": "4.75"},
        ],
        "cpi_as_of": "2026-09-01",
        "cpi": [
            {"month": "2009-11-01", "change_percent": "0.2"},
            {"month": "2009-12-01", "change_percent": "0.2"},
        ],
    }


async def test_market_series_refuses_more_months_than_the_history_holds(
    settings: Settings, history: MarketHistory
) -> None:
    async with client(settings, history) as c:
        result = await c.call_tool("market_series", {"prime_months": 121, "cpi_months": 12})
    assert result.is_error
    assert "prime_months" in result.content[0].text


async def test_rates_resources_return_json_with_as_of(
    settings: Settings, history: MarketHistory
) -> None:
    async with client(settings, history) as c:
        boi = json.loads((await c.read_resource("rates://boi/history")).contents[0].text)
        cpi = json.loads((await c.read_resource("rates://cpi/history")).contents[0].text)
        current = json.loads((await c.read_resource("rates://current")).contents[0].text)
    assert boi["as_of"] == "2026-10-20"
    assert len(boi["months"]) == 120
    assert boi["months"][1] == {"month": "2000-02-01", "boi_rate": "0.125"}
    assert cpi["as_of"] == "2026-09-01"
    assert cpi["months"][0] == {"month": "2000-01-01", "inflation": "0.002"}
    assert current == {
        "boi_rate": "3.25",
        "prime": "4.75",
        "rate_as_of": "2026-10-20",
        "cpi_as_of": "2026-09-01",
        "consumer_rate": "7.9",
        "consumer_rate_month": "2026-08-01",
    }


async def test_propose_term_returns_the_term_and_its_first_payment_in_agorot(
    settings: Settings, history: MarketHistory
) -> None:
    arguments = {"principal": 31000, "payment_limit": 1000}
    async with client(settings, history) as c:
        result = await c.call_tool("propose_term", arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["term_months"] % 6 == 0
    first = Decimal(str(result.structured_content["first_payment"]))
    assert first < 1000 and first == first.quantize(Decimal("0.01"))


async def test_propose_offer_term_proposes_the_maximum_when_none_is_under_the_limit(
    settings: Settings, history: MarketHistory
) -> None:
    arguments = {"track": {**PRIME_TRACK, "term_months": 84}, "payment_limit": 100}
    async with client(settings, history) as c:
        result = await c.call_tool("propose_offer_term", arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["term_months"] == 84


async def test_largest_comfortable_loan_is_null_for_a_ceiling_of_200(
    settings: Settings, history: MarketHistory
) -> None:
    async with client(settings, history) as c:
        result = await c.call_tool(
            "largest_comfortable_loan", {"payment_ceiling": 200, "term_months": 60}
        )
    assert not result.is_error, result.content
    assert result.structured_content == {"loan_amount": None}
