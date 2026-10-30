"""The agent's own tools save the person's data and refuse a recommendation outside the engine's
bounds, with messages the model can act on."""

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from fakes import (
    ASSESSED_BOUNDS,
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
from loan_agent.application.check_tools import ASKED_RESULT, CheckTools, ToolDeps, ToolError
from loan_agent.domain.models import Check, Goal, Profile
from loan_agent.ports.engine import EngineError, OfferTerm
from loan_agent.ports.events import CHART_SHOWN, QUESTION_ASKED

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
    "variable_income_minimum": "2000",
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
    await world.tools.set_goal("car", "120000")
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    await world.tools.save_option({"tracks": [PRIME_TRACK]}, "published_average")
    await world.tools.save_option({"tracks": [BALLOON_TRACK]}, "offer", "Bank", "2026-10-20")
    world.sink.events.clear()
    world.clock.value = NOW + timedelta(minutes=5)


async def test_update_profile_merges_and_emits(world: World) -> None:
    await world.tools.update_profile(net_fixed_income="18000")
    summary = await world.tools.update_profile(variable_income_minimum=1500, savings=70000)

    stored, updated_at = await world.profiles.get(PERSON)
    assert stored == Profile(
        net_fixed_income=Decimal(18000),
        variable_income_minimum=Decimal(1500),
        savings=Decimal(70000),
    )
    assert updated_at == NOW
    event = world.sink.events[-1]
    assert (event.check_id, event.type) == (CHECK, "profile.updated")
    assert event.data == {
        "profile": {
            "net_fixed_income": "18000",
            "variable_income": None,
            "variable_income_minimum": "1500",
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
    summary = await world.tools.set_goal("car", "55000")

    check = await world.checks.get(PERSON, CHECK)
    assert check.goal == Goal("car", Decimal(55000))
    assert world.sink.events[-1].type == "goal.set"
    assert world.sink.events[-1].data == {"purpose": "car", "price": "55000"}
    assert "price: 55000" in summary.splitlines()


async def test_set_goal_rejects_zero_price_naming_field(world: World) -> None:
    with pytest.raises(ToolError, match="price must be greater than zero"):
        await world.tools.set_goal("car", "0")

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
    # The model reads amounts to the shekel, as the person does.
    assert {"first_payment: 1888", "worst_peak_payment: 2039", "total_paid: 90623"} <= set(lines)
    assert "schedule" not in summary


async def test_save_option_engine_error_reaches_model(world: World) -> None:
    world.engine.simulate_error = EngineError("tracks.0.term_months: must be at most 96")

    with pytest.raises(ToolError, match="tracks.0.term_months: must be at most 96"):
        await world.tools.save_option({"tracks": [PRIME_TRACK]}, "offer", "Bank", "2026-10-20")

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
    await world.tools.save_option({"tracks": [PRIME_TRACK]}, "offer", "Bank", "2026-10-20")
    world.sink.events.clear()

    with pytest.raises(ToolError) as refused:
        await world.tools.present_recommendation("option-1", REASONING)

    message = str(refused.value)
    assert "variable_income_minimum" not in message
    for missing in (
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


async def test_recommendation_refused_when_reasoning_names_an_option_id(world: World) -> None:
    await ready_for_recommendation(world)

    with pytest.raises(ToolError, match="names an option by its id"):
        await world.tools.present_recommendation("option-1", "ממליץ על option-1 כי הוא זול")

    assert world.recommendations.rows == {}


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
                "variable_income_minimum": "2000",
                "fixed_expenses": "9000",
                "existing_loan_payments": "800",
            },
        ),
        (
            "size",
            {
                "goal_price": Decimal(120000),
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
            "variable_income_minimum_counted",
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


async def test_ask_emits_the_question_and_ends_with_the_fixed_result(world: World) -> None:
    question = {"field": "savings", "text": None, "choices": None}
    result = await world.tools.ask(question, "כדי לדעת כמה להשאיר בצד")
    assert result == ASKED_RESULT
    (event,) = [e for e in world.sink.events if e.type == QUESTION_ASKED]
    assert event.data == {"question": question, "lead_in": "כדי לדעת כמה להשאיר בצד"}


async def test_ask_refuses_a_stored_profile_field_naming_its_value(world: World) -> None:
    await world.profiles.save(PERSON, Profile().merged({"savings": "12000"}))
    with pytest.raises(ToolError, match="savings.*12000"):
        await world.tools.ask({"field": "savings", "text": None, "choices": None}, None)
    assert not [e for e in world.sink.events if e.type == QUESTION_ASKED]


async def test_ask_refuses_the_minimum_when_variable_income_is_zero(world: World) -> None:
    await world.profiles.save(PERSON, Profile().merged({"variable_income": "0"}))
    with pytest.raises(ToolError, match="not needed"):
        await world.tools.ask(
            {"field": "variable_income_minimum", "text": None, "choices": None}, None
        )


async def test_ask_allows_a_goal_field_and_a_free_question(world: World) -> None:
    await world.tools.ask({"field": "price", "text": None, "choices": None}, None)
    await world.tools.ask(
        {"field": None, "text": "חדש או משומש?", "choices": ["חדש", "משומש"]}, None
    )
    assert len([e for e in world.sink.events if e.type == QUESTION_ASKED]) == 2


async def test_an_example_before_the_whole_profile_is_refused_naming_what_is_missing(
    world: World,
) -> None:
    await world.tools.update_profile(net_fixed_income="18000", variable_income="0")
    world.engine.simulations = [PRIME_SIMULATION]

    with pytest.raises(ToolError, match="ask the person for: savings, fixed_expenses"):
        await world.tools.save_option({"tracks": [PRIME_TRACK]}, "published_average")

    assert world.engine.calls == []
    assert await world.options.list(CHECK) == []


async def test_example_above_ceiling_is_refused_while_an_offer_is_saved(world: World) -> None:
    await world.tools.update_profile(**COMPLETE_PROFILE)
    world.engine.bounds = replace(ASSESSED_BOUNDS, payment_ceiling=Decimal(100))
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION]

    with pytest.raises(ToolError, match="above the payment_ceiling of 100"):
        await world.tools.save_option({"tracks": [PRIME_TRACK]}, "published_average")
    await world.tools.save_option({"tracks": [PRIME_TRACK]}, "offer", "Bank", "2026-10-20")

    saved = [option.source for options in world.options.rows.values() for option in options]
    assert saved == ["offer"]


async def test_a_recommendation_records_the_loan_it_takes_and_the_cushion_that_leaves(
    world: World,
) -> None:
    await ready_for_recommendation(world)
    world.engine.simulations = [PRIME_SIMULATION]
    larger = {**PRIME_TRACK, "principal": "90000"}
    await world.tools.save_option({"tracks": [larger]}, "offer")

    await world.tools.present_recommendation("option-3", REASONING)

    recommendation = world.recommendations.rows[CHECK]
    assert recommendation.loan_amount == Decimal(90000)
    assert recommendation.cushion_kept == Decimal(40000)
    sizing = world.sink.events[-1].data["sizing"]
    assert (sizing["loan_amount"], sizing["cushion_kept"]) == ("90000.00", "40000.00")


async def test_a_loan_above_the_price_keeps_no_more_than_the_savings(world: World) -> None:
    await ready_for_recommendation(world)
    world.engine.simulations = [PRIME_SIMULATION]
    larger = {**PRIME_TRACK, "principal": "200000"}
    await world.tools.save_option({"tracks": [larger]}, "offer")

    await world.tools.present_recommendation("option-3", REASONING)

    assert world.recommendations.rows[CHECK].cushion_kept == Decimal(70000)


async def test_saving_an_offer_tells_the_model_to_recommend_again(world: World) -> None:
    await ready_for_recommendation(world)
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION]

    offer = await world.tools.save_option({"tracks": [PRIME_TRACK]}, "offer")
    example = await world.tools.save_option({"tracks": [PRIME_TRACK]}, "published_average")

    assert "present_recommendation" in offer
    assert "present_recommendation" not in example


async def test_saving_an_offer_before_the_whole_profile_asks_for_no_recommendation(
    world: World,
) -> None:
    world.engine.simulations = [PRIME_SIMULATION]

    result = await world.tools.save_option({"tracks": [PRIME_TRACK]}, "offer")

    assert "present_recommendation" not in result


async def test_an_example_never_beats_a_real_offer_within_the_bounds(world: World) -> None:
    await ready_for_recommendation(world)

    with pytest.raises(ToolError, match="prefer the real offer"):
        await world.tools.present_recommendation("option-1", REASONING, "option-2")

    assert CHECK not in world.recommendations.rows


async def test_an_example_is_preferred_when_the_offer_is_above_the_ceiling(world: World) -> None:
    await ready_for_recommendation(world)
    above = replace(
        BALLOON_SIMULATION.figures, peak_payment=Decimal(99999), worst_peak_payment=None
    )
    world.options.rows[CHECK][1] = replace(world.options.rows[CHECK][1], summary=above)

    await world.tools.present_recommendation("option-1", REASONING)

    assert world.recommendations.rows[CHECK].preferred_option_id == "option-1"


async def test_an_offer_with_a_maximum_above_its_comfortable_term_is_refused(
    world: World,
) -> None:
    await world.tools.update_profile(**COMPLETE_PROFILE)
    world.engine.simulations = [PRIME_SIMULATION]
    long_offer = {"tracks": [{**PRIME_TRACK, "term_months": 84}]}

    with pytest.raises(ToolError, match="save it with term_months 24"):
        await world.tools.save_option(long_offer, "offer", "Fund", None, 84)

    assert await world.options.list(CHECK) == []
    _, asked = world.engine.calls[-1]
    assert asked["track"]["term_months"] == 84


async def test_an_offer_at_its_comfortable_term_asks_the_engine_with_the_maximum(
    world: World,
) -> None:
    await world.tools.update_profile(**COMPLETE_PROFILE)
    world.engine.simulations = [PRIME_SIMULATION]
    offer = {"tracks": [{**PRIME_TRACK, "term_months": 24}]}

    await world.tools.save_option(offer, "offer", "Fund", None, 84)

    (option,) = await world.options.list(CHECK)
    assert option.loan == offer
    _, asked = world.engine.calls[-1]
    assert asked["track"]["term_months"] == 84


async def test_an_offer_no_term_fits_is_saved_at_its_maximum(world: World) -> None:
    await world.tools.update_profile(**COMPLETE_PROFILE)
    world.engine.offer_terms = OfferTerm(term_months=84, comfortable=False)
    world.engine.simulations = [PRIME_SIMULATION]

    await world.tools.save_option(
        {"tracks": [{**PRIME_TRACK, "term_months": 84}]}, "offer", "Fund", None, 84
    )

    assert len(await world.options.list(CHECK)) == 1


async def test_an_offer_with_a_maximum_needs_the_whole_profile(world: World) -> None:
    with pytest.raises(ToolError, match="a term up to a maximum comes only after"):
        await world.tools.save_option({"tracks": [PRIME_TRACK]}, "offer", "Fund", None, 84)


async def test_the_maximum_is_refused_on_an_example(world: World) -> None:
    with pytest.raises(ToolError, match="belongs to a real offer"):
        await world.tools.save_option(
            {"tracks": [PRIME_TRACK]}, "published_average", None, None, 84
        )


async def test_the_engine_refusing_an_offer_term_reaches_the_model(world: World) -> None:
    await world.tools.update_profile(**COMPLETE_PROFILE)
    world.engine.simulations = [PRIME_SIMULATION]
    world.engine.offer_term_error = EngineError("term_months too long")

    with pytest.raises(ToolError, match="term_months too long"):
        await world.tools.save_option({"tracks": [PRIME_TRACK]}, "offer", "Fund", None, 84)


async def test_show_chart_emits_the_engine_series_for_the_page(world: World) -> None:
    result = await world.tools.show_chart("cpi", 12)

    assert world.engine.calls == [("market_series", {"months": 12})]
    event = world.sink.events[-1]
    assert event.type == CHART_SHOWN
    assert event.data["series"] == "cpi"
    assert event.data["as_of"] == "2026-09-01"
    points = event.data["points"]
    assert len(points) == 12
    assert points[-1] == {"month": "2026-09-01", "value": "-0.5"}
    assert "2025-10 to 2026-09" in result
    assert "-0.5" not in result


async def test_show_chart_prime_uses_the_rate_date(world: World) -> None:
    await world.tools.show_chart("prime", 60)

    event = world.sink.events[-1]
    assert event.data["as_of"] == "2026-10-30"
    assert event.data["points"][-1] == {"month": "2026-10-01", "value": "4.75"}


async def test_show_chart_refuses_an_unknown_series(world: World) -> None:
    with pytest.raises(ToolError, match="series must be one of prime, cpi"):
        await world.tools.show_chart("dollar", 12)
    assert world.sink.events == []


async def test_show_chart_passes_the_engine_refusal_to_the_model(world: World) -> None:
    world.engine.market_error = EngineError("prime_months: less than or equal to 120")

    with pytest.raises(ToolError, match="less than or equal to 120.*call show_chart again"):
        await world.tools.show_chart("prime", 500)
