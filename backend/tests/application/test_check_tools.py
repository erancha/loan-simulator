"""The agent's own tools save the person's data and refuse a recommendation outside the engine's
bounds, with messages the model can act on."""

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from fakes import (
    BALLOON_SIMULATION,
    NOW,
    PRIME_SIMULATION,
    Clock,
    FakeLoanEngine,
    Ids,
    InMemoryCheckRepository,
    InMemoryOptionRepository,
    InMemoryProfileRepository,
    InMemoryRecommendationRepository,
    RecordingSink,
)
from loan_agent.application.check_tools import CheckTools, ToolDeps, ToolError
from loan_agent.domain.models import Check, Goal, Profile
from loan_agent.ports.engine import EngineError

PERSON = "1001"
CHECK = "check-1"
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
COMPLETE_PROFILE = {
    "net_fixed_income": "18000",
    "variable_income": "4000",
    "variable_income_stable": True,
    "fixed_expenses": "9000",
    "existing_loan_payments": "800",
    "savings": "70000",
}
REASONING = "Lowest total cost under the ceiling"


@dataclass
class World:
    clock: Clock
    profiles: InMemoryProfileRepository
    checks: InMemoryCheckRepository
    options: InMemoryOptionRepository
    recommendations: InMemoryRecommendationRepository
    engine: FakeLoanEngine
    sink: RecordingSink
    tools: CheckTools


@pytest.fixture
async def world() -> World:
    clock = Clock()
    profiles = InMemoryProfileRepository(clock)
    checks = InMemoryCheckRepository()
    options = InMemoryOptionRepository()
    recommendations = InMemoryRecommendationRepository()
    engine = FakeLoanEngine()
    sink = RecordingSink()
    await checks.add(Check(CHECK, PERSON, NOW, None, None))
    deps = ToolDeps(
        profiles=profiles,
        checks=checks,
        options=options,
        recommendations=recommendations,
        engine=engine,
        sink=sink,
        clock=clock,
        new_id=Ids("option"),
    )
    return World(
        clock,
        profiles,
        checks,
        options,
        recommendations,
        engine,
        sink,
        CheckTools(PERSON, CHECK, deps),
    )


async def ready_for_recommendation(world: World) -> None:
    """A complete profile, a goal, and two options: the prime track and the balloon track."""
    await world.tools.update_profile(**COMPLETE_PROFILE)
    await world.tools.set_goal("car", "160000", "40000")
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    await world.tools.save_option({"tracks": [PRIME_TRACK]}, "published_average")
    await world.tools.save_option({"tracks": [BALLOON_TRACK]}, "offer", "Bank", "2026-10-20")
    world.sink.events.clear()
    world.clock.value = NOW + timedelta(minutes=5)


async def test_update_profile_merges_and_emits(world: World) -> None:
    await world.tools.update_profile(net_fixed_income="18000")
    summary = await world.tools.update_profile(variable_income_stable=True, savings=70000)

    stored, updated_at = await world.profiles.get(PERSON)
    assert stored == Profile(
        net_fixed_income=Decimal(18000), variable_income_stable=True, savings=Decimal(70000)
    )
    assert updated_at == NOW
    event = world.sink.events[-1]
    assert (event.check_id, event.type) == (CHECK, "profile.updated")
    assert event.data == {
        "profile": {
            "net_fixed_income": "18000",
            "variable_income": None,
            "variable_income_stable": True,
            "fixed_expenses": None,
            "existing_loan_payments": None,
            "savings": "70000",
        },
        "missing": ["variable_income", "fixed_expenses", "existing_loan_payments"],
    }
    assert "net_fixed_income: 18000" in summary.splitlines()
    assert "missing: variable_income, fixed_expenses, existing_loan_payments" in (
        summary.splitlines()
    )


async def test_update_profile_rejects_negative_naming_field(world: World) -> None:
    with pytest.raises(ToolError, match="fixed_expenses cannot be negative"):
        await world.tools.update_profile(fixed_expenses="-100")

    assert world.profiles.rows == {}
    assert world.sink.events == []


async def test_set_goal_stores_on_check_and_emits(world: World) -> None:
    summary = await world.tools.set_goal("car", "55000", "0")

    check = await world.checks.get(PERSON, CHECK)
    assert check.goal == Goal("car", Decimal(55000), Decimal(0))
    assert world.sink.events[-1].type == "goal.set"
    assert world.sink.events[-1].data == {
        "purpose": "car",
        "price": "55000",
        "trade_in_value": "0",
    }
    assert "price: 55000" in summary.splitlines()


async def test_set_goal_rejects_zero_price_naming_field(world: World) -> None:
    with pytest.raises(ToolError, match="price must be greater than zero"):
        await world.tools.set_goal("car", "0", "0")

    assert (await world.checks.get(PERSON, CHECK)).goal is None


async def test_save_option_stores_engine_figures_and_emits_structured(world: World) -> None:
    world.engine.simulations = [PRIME_SIMULATION]

    summary = await world.tools.save_option(
        {"tracks": [PRIME_TRACK]}, "offer", lender="Bank", offer_date="2026-10-20"
    )

    assert world.engine.calls == [("simulate", {"tracks": [PRIME_TRACK]})]
    (option,) = await world.options.list(CHECK)
    assert option.id == "option-1"
    assert option.summary == PRIME_SIMULATION.figures
    assert option.loan == {"tracks": [PRIME_TRACK]}
    assert (option.source, option.lender, option.offer_date.isoformat()) == (
        "offer",
        "Bank",
        "2026-10-20",
    )
    event = world.sink.events[-1]
    assert event.type == "option.saved"
    assert event.data["option_id"] == "option-1"
    assert event.data["result"] == PRIME_SIMULATION.structured
    assert event.data["figures"] == {
        "first_payment": "1887.99",
        "peak_payment": "1887.99",
        "worst_peak_payment": "2038.63",
        "worst_start": "2022-04-01",
        "worst_end": "2026-03-01",
        "balloon_due": None,
        "total_paid": "90623.31",
        "rate_as_of": "2026-10-26",
        "cpi_as_of": "2026-09-01",
    }
    lines = summary.splitlines()
    assert "option_id: option-1" in lines
    assert "worst_peak_payment: 2038.63" in lines
    assert "schedule" not in summary


async def test_save_option_engine_error_reaches_model(world: World) -> None:
    world.engine.simulate_error = EngineError("tracks.0.term_months: must be at most 96")

    with pytest.raises(ToolError, match="tracks.0.term_months: must be at most 96"):
        await world.tools.save_option({"tracks": [PRIME_TRACK]}, "published_average")

    assert await world.options.list(CHECK) == []
    assert world.sink.events == []


@pytest.mark.parametrize(
    ("source", "offer_date", "field"),
    [("bank", None, "source"), ("offer", "20/10/2026", "offer_date")],
)
async def test_save_option_rejects_bad_argument_naming_field(
    world: World, source: str, offer_date: str | None, field: str
) -> None:
    with pytest.raises(ToolError, match=field):
        await world.tools.save_option({"tracks": [PRIME_TRACK]}, source, None, offer_date)

    assert world.engine.calls == []


async def test_recommendation_requires_profile_and_goal_naming_missing(world: World) -> None:
    await world.tools.update_profile(net_fixed_income="18000", variable_income="0")
    world.engine.simulations = [PRIME_SIMULATION]
    await world.tools.save_option({"tracks": [PRIME_TRACK]}, "published_average")
    world.sink.events.clear()

    with pytest.raises(ToolError) as refused:
        await world.tools.present_recommendation("option-1", REASONING)

    message = str(refused.value)
    for missing in (
        "variable_income_stable",
        "fixed_expenses",
        "existing_loan_payments",
        "savings",
        "goal",
    ):
        assert missing in message
    assert "ask the person for" in message
    assert world.recommendations.rows == {}
    assert (await world.checks.get(PERSON, CHECK)).profile_snapshot_at is None
    assert world.sink.events == []


async def test_recommendation_refused_above_ceiling(world: World) -> None:
    await ready_for_recommendation(world)
    world.engine.bounds = replace(world.engine.bounds, payment_ceiling=Decimal(1550))
    over = replace(PRIME_SIMULATION.figures, worst_peak_payment=Decimal(1600))
    world.options.rows[CHECK][0] = replace(world.options.rows[CHECK][0], summary=over)

    with pytest.raises(ToolError) as refused:
        await world.tools.present_recommendation("option-1", REASONING, "option-2")

    message = str(refused.value)
    assert "option-1" in message
    assert "1600" in message
    assert "1550" in message
    assert world.recommendations.rows == {}
    assert world.sink.events == []


async def test_recommendation_refused_below_sized_loan(world: World) -> None:
    await ready_for_recommendation(world)
    world.engine.sizing = replace(world.engine.sizing, loan_amount=Decimal("85000.00"))

    with pytest.raises(ToolError) as refused:
        await world.tools.present_recommendation("option-1", REASONING)

    message = str(refused.value)
    assert "option-1" in message
    assert "80000" in message
    assert "85000.00" in message
    assert world.recommendations.rows == {}


async def test_sized_loan_beyond_engine_maximum_tells_model_purchase_is_out_of_range(
    world: World,
) -> None:
    await ready_for_recommendation(world)
    world.engine.sizing = replace(world.engine.sizing, loan_amount=Decimal("180000.00"))

    with pytest.raises(ToolError) as refused:
        await world.tools.present_recommendation("option-1", REASONING)

    message = str(refused.value)
    assert "180000.00" in message
    assert "above the engine's maximum loan" in message
    assert "outside the range this simulator prices" in message
    assert "larger down payment or a cheaper goal" in message
    assert world.recommendations.rows == {}


async def test_recommendation_refused_when_no_loan_needed(world: World) -> None:
    await ready_for_recommendation(world)
    world.engine.sizing = replace(world.engine.sizing, loan_amount=Decimal("0.00"))

    with pytest.raises(ToolError, match="no loan is needed"):
        await world.tools.present_recommendation("option-1", REASONING)

    assert world.recommendations.rows == {}


async def test_recommendation_refused_for_unknown_option(world: World) -> None:
    await ready_for_recommendation(world)

    with pytest.raises(ToolError, match="alternative_option_id.*option-9"):
        await world.tools.present_recommendation("option-1", REASONING, "option-9")


async def test_recommendation_figures_come_from_engine(world: World) -> None:
    await ready_for_recommendation(world)
    reasoning = "Pay 999 a month and 12345 in total; cheapest by far"

    summary = await world.tools.present_recommendation("option-2", reasoning, "option-1")

    recommendation = world.recommendations.rows[CHECK]
    assert recommendation.preferred_option_id == "option-2"
    assert recommendation.alternative_option_id == "option-1"
    assert recommendation.reasoning == reasoning
    assert recommendation.loan_amount == Decimal("80000.00")
    assert recommendation.payment_ceiling == Decimal("4700.00")
    assert recommendation.min_cushion == Decimal("18000.00")
    assert recommendation.cushion_kept == Decimal("30000.00")
    assert recommendation.created_at == world.clock.value
    assert world.engine.calls[-2:] == [
        (
            "assess",
            {
                "net_fixed_income": "18000",
                "variable_income": "4000",
                "variable_income_stable": True,
                "fixed_expenses": "9000",
                "existing_loan_payments": "800",
            },
        ),
        (
            "size",
            {
                "goal_price": Decimal(160000),
                "trade_in_value": Decimal(40000),
                "savings": Decimal(70000),
                "min_cushion": Decimal("18000.00"),
            },
        ),
    ]
    check = await world.checks.get(PERSON, CHECK)
    assert check.profile_snapshot_at == NOW
    (event,) = world.sink.events
    assert event.type == "recommendation.presented"
    assert event.data["bounds"] == {
        "payment_ceiling": "4700.00",
        "min_cushion": "18000.00",
        "reasons": [
            "variable_income_half_counted",
            "ceiling_by_disposable_income",
            "existing_loans_deducted",
        ],
    }
    assert event.data["sizing"] == {
        "loan_amount": "80000.00",
        "savings_used": "40000.00",
        "cushion_kept": "30000.00",
        "spare_savings": "0.00",
    }
    preferred = event.data["preferred"]
    alternative = event.data["alternative"]
    assert isinstance(preferred, dict) and isinstance(alternative, dict)
    assert preferred["option_id"] == "option-2"
    assert preferred["figures"]["total_paid"] == "96049.73"
    assert alternative["figures"]["total_paid"] == "90623.31"
    assert event.data["reasoning"] == reasoning
    assert "999" not in summary
    assert "12345" not in summary


async def test_balloon_option_judged_on_recurring_payment(world: World) -> None:
    await ready_for_recommendation(world)
    world.engine.bounds = replace(world.engine.bounds, payment_ceiling=Decimal(1550))
    balloon = replace(BALLOON_SIMULATION.figures, balloon_due=Decimal(10000))
    world.options.rows[CHECK][1] = replace(world.options.rows[CHECK][1], summary=balloon)

    await world.tools.present_recommendation("option-2", REASONING)

    assert world.recommendations.rows[CHECK].preferred_option_id == "option-2"
