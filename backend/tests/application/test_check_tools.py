"""The agent's own tools save the loan, its term, its ceiling and the finances on the check, and
refuse a recommendation that breaks the rules, with messages the model can act on: every named
option borrows the loan amount, and with a ceiling every one fits it."""

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
    InMemoryRecommendationRepository,
    RecordingSink,
)
from loan_agent.application.check_tools import ASKED_RESULT, CheckTools, ToolDeps, ToolError
from loan_agent.domain.models import Check, Finances, LoanRequest
from loan_agent.ports.engine import EngineError, OfferTerm, ProposedTerm, Simulation
from loan_agent.ports.events import (
    CEILING_SET,
    CHART_SHOWN,
    EXAMPLES_REMOVED,
    FINANCES_UPDATED,
    LOAN_SET,
    QUESTION_ASKED,
    RECOMMENDATION_PRESENTED,
    TERM_SET,
)

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
REASONING = "העלות הכוללת הנמוכה ביותר"


def worst_case(simulation: Simulation, payment: str) -> Simulation:
    return replace(
        simulation, figures=replace(simulation.figures, worst_peak_payment=Decimal(payment))
    )


@dataclass
class World:
    clock: Clock
    checks: InMemoryCheckRepository
    options: InMemoryOptionRepository
    recommendations: InMemoryRecommendationRepository
    engine: FakeLoanEngine
    sink: RecordingSink
    tools: CheckTools

    async def check(self) -> Check:
        return await self.checks.get(PERSON, CHECK)

    def events_of(self, type: str) -> list[object]:
        return [event.data for event in self.sink.events if event.type == type]


@pytest.fixture
async def world() -> World:
    clock = Clock()
    checks = InMemoryCheckRepository()
    options = InMemoryOptionRepository()
    recommendations = InMemoryRecommendationRepository()
    engine = FakeLoanEngine()
    sink = RecordingSink()
    await checks.add(Check(CHECK, PERSON, NOW, None, None, None, None, Finances()))
    deps = ToolDeps(
        checks=checks,
        options=options,
        recommendations=recommendations,
        engine=engine,
        sink=sink,
        clock=clock,
        new_id=Ids("option"),
    )
    return World(
        clock, checks, options, recommendations, engine, sink, CheckTools(PERSON, CHECK, deps)
    )


async def ready_for_recommendation(world: World) -> None:
    """A loan of 80,000 at 48 months and two examples of it, before any real offer: the prime
    track, the cheaper in total, and the balloon track."""
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(48)
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    await world.tools.save_option({"tracks": [PRIME_TRACK]})
    await world.tools.save_option({"tracks": [BALLOON_TRACK]})
    world.sink.events.clear()
    world.engine.calls.clear()
    world.clock.value = NOW + timedelta(minutes=5)


async def test_set_loan_stores_the_loan_and_emits(world: World) -> None:
    summary = await world.tools.set_loan("רכב", "60000")

    assert (await world.check()).loan == LoanRequest("רכב", Decimal(60000))
    assert world.events_of(LOAN_SET) == [{"purpose": "רכב", "amount": "60000"}]
    assert {"purpose: רכב", "amount: 60000"} <= set(summary.splitlines())


async def test_set_loan_saves_a_ceiling_named_with_the_loan_as_stated(world: World) -> None:
    summary = await world.tools.set_loan("רכב", "24000", "1000")

    check = await world.check()
    assert (check.payment_ceiling, check.ceiling_source) == (Decimal(1000), "stated")
    assert [event.type for event in world.sink.events] == [LOAN_SET, CEILING_SET]
    assert "payment_ceiling: 1000" in summary.splitlines()


async def test_set_loan_with_a_ceiling_of_zero_saves_nothing(world: World) -> None:
    with pytest.raises(ToolError, match="payment_ceiling must be greater than zero"):
        await world.tools.set_loan("רכב", "24000", "0")

    check = await world.check()
    assert (check.loan, check.payment_ceiling) == (None, None)
    assert world.sink.events == []


async def test_set_loan_without_a_purpose_keeps_it_none(world: World) -> None:
    await world.tools.set_loan(None, 100000)

    assert (await world.check()).loan == LoanRequest(None, Decimal(100000))


async def test_set_loan_refuses_an_amount_below_the_minimum(world: World) -> None:
    world.engine.suggest_error = EngineError(
        "principal: Input should be greater than or equal to 10000"
    )

    with pytest.raises(ToolError, match="greater than or equal to 10000"):
        await world.tools.set_loan(None, "5000")

    assert (await world.check()).loan is None
    assert world.sink.events == []


@pytest.mark.parametrize("amount", ["0", "-100", "abc", 1.5])
async def test_set_loan_refuses_an_amount_that_is_not_a_positive_number(
    world: World, amount: object
) -> None:
    with pytest.raises(ToolError, match="amount"):
        await world.tools.set_loan(None, amount)

    assert (await world.check()).loan is None


async def test_ask_term_proposes_60_months_for_a_car(world: World) -> None:
    await world.tools.set_loan("רכב", "60000")
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    world.engine.calls.clear()

    result = await world.tools.ask_term(None)

    assert result == ASKED_RESULT
    assert world.events_of(QUESTION_ASKED) == [
        {
            "question": {"kind": "term", "term_months": 60, "first_payment": "1887.99"},
            "lead_in": None,
        }
    ]
    assert world.engine.calls[0] == (
        "suggest",
        {"principal": Decimal(60000), "term_months": 60},
    )
    assert [name for name, _ in world.engine.calls] == ["suggest", "simulate", "simulate"]


async def test_a_ceiling_decides_a_cars_term_too(world: World) -> None:
    await world.tools.set_loan("רכב", "24000")
    await world.tools.set_ceiling("1000")
    world.engine.comfortable_terms = 24
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]

    await world.tools.ask_term(None)

    (asked,) = world.events_of(QUESTION_ASKED)
    assert isinstance(asked, dict) and asked["question"]["term_months"] == 24
    assert "comfortable_term" in [name for name, _ in world.engine.calls]


async def test_ask_term_proposes_the_first_payment_term_without_a_ceiling(world: World) -> None:
    await world.tools.set_loan("שיפוץ", "100000")
    world.engine.proposed = ProposedTerm(term_months=84, first_payment=Decimal("1554.00"))
    world.engine.calls.clear()

    await world.tools.ask_term(None)

    assert world.engine.calls == [
        ("propose_term", {"principal": Decimal(100000), "payment_limit": Decimal(1000)})
    ]
    assert world.events_of(QUESTION_ASKED) == [
        {
            "question": {"kind": "term", "term_months": 84, "first_payment": "1554.00"},
            "lead_in": None,
        }
    ]


@pytest.mark.parametrize(("found", "proposed"), [(72, 72), (None, 84)])
async def test_ask_term_uses_the_worst_case_search_with_a_ceiling(
    world: World, found: int | None, proposed: int
) -> None:
    await world.tools.set_loan(None, "60000")
    await world.tools.set_ceiling("1000")
    world.engine.comfortable_terms = found
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    world.engine.calls.clear()

    await world.tools.ask_term(None)

    assert world.engine.calls[0] == (
        "comfortable_term",
        {"principal": Decimal(60000), "payment_ceiling": Decimal(1000), "any_track": False},
    )
    assert world.engine.calls[1] == (
        "suggest",
        {"principal": Decimal(60000), "term_months": proposed},
    )
    (asked,) = world.events_of(QUESTION_ASKED)
    assert isinstance(asked, dict) and asked["question"]["term_months"] == proposed


async def test_ask_term_shows_the_term_the_person_typed(world: World) -> None:
    await world.tools.set_loan(None, "100000")
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    world.engine.calls.clear()

    await world.tools.ask_term(36)

    assert world.engine.calls[0] == (
        "suggest",
        {"principal": Decimal(100000), "term_months": 36},
    )


async def test_the_term_the_last_card_showed_is_a_confirmation_not_a_new_card(
    world: World,
) -> None:
    await world.tools.set_loan(None, "60000")
    world.engine.proposed = ProposedTerm(term_months=78, first_payment=Decimal("986.03"))
    await world.tools.ask_term(None)

    with pytest.raises(ToolError, match="call set_term with 78"):
        await world.tools.ask_term(78)

    assert len(world.events_of(QUESTION_ASKED)) == 1


async def test_another_term_after_a_card_gets_its_own_card(world: World) -> None:
    await world.tools.set_loan(None, "60000")
    world.engine.proposed = ProposedTerm(term_months=78, first_payment=Decimal("986.03"))
    await world.tools.ask_term(None)
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]

    await world.tools.ask_term(48)

    first, second = world.events_of(QUESTION_ASKED)
    assert isinstance(first, dict) and first["question"]["term_months"] == 78
    assert isinstance(second, dict) and second["question"]["term_months"] == 48


async def test_ask_offer_puts_the_form_on_the_screen_with_what_was_said(world: World) -> None:
    await world.tools.set_loan("רכב", "60000")
    track = {"rate_kind": "prime", "rate": "0.5", "cpi_linked": False}

    result = await world.tools.ask_offer("קרן הפנסיה", [track], 84)

    assert result == ASKED_RESULT
    assert world.events_of(QUESTION_ASKED) == [
        {
            "question": {
                "kind": "offer",
                "lender": "קרן הפנסיה",
                "tracks": [track],
                "max_term_months": 84,
            },
            "lead_in": None,
        }
    ]


async def test_ask_offer_with_nothing_said_opens_an_empty_form(world: World) -> None:
    await world.tools.set_loan(None, "60000")

    await world.tools.ask_offer(None, [], None)

    assert world.events_of(QUESTION_ASKED) == [
        {
            "question": {"kind": "offer", "lender": None, "tracks": [], "max_term_months": None},
            "lead_in": None,
        }
    ]


async def test_ask_offer_before_a_loan_names_set_loan(world: World) -> None:
    with pytest.raises(ToolError, match="set_loan"):
        await world.tools.ask_offer(None, [], None)
    assert world.events_of(QUESTION_ASKED) == []


async def test_ask_term_needs_a_loan(world: World) -> None:
    with pytest.raises(ToolError, match="set_loan"):
        await world.tools.ask_term(None)

    assert world.sink.events == []


async def test_set_term_stores_and_emits(world: World) -> None:
    await world.tools.set_loan(None, "60000")

    summary = await world.tools.set_term(60)

    assert (await world.check()).term_months == 60
    assert world.events_of(TERM_SET) == [{"term_months": 60}]
    assert "term_months: 60" in summary.splitlines()


@pytest.mark.parametrize("term", [5, 85])
async def test_set_term_refuses_a_term_outside_6_to_84(world: World, term: int) -> None:
    await world.tools.set_loan(None, "60000")

    with pytest.raises(ToolError, match="between 6 and 84"):
        await world.tools.set_term(term)
    with pytest.raises(ToolError, match="between 6 and 84"):
        await world.tools.ask_term(term)

    assert (await world.check()).term_months is None


async def test_set_ceiling_stores_a_stated_ceiling(world: World) -> None:
    summary = await world.tools.set_ceiling("1500")

    check = await world.check()
    assert (check.payment_ceiling, check.ceiling_source) == (Decimal(1500), "stated")
    assert world.events_of(CEILING_SET) == [{"payment_ceiling": "1500", "ceiling_source": "stated"}]
    assert "payment_ceiling: 1500" in summary.splitlines()


@pytest.mark.parametrize("amount", ["0", "-10"])
async def test_set_ceiling_refuses_a_ceiling_that_is_not_positive(
    world: World, amount: str
) -> None:
    with pytest.raises(ToolError, match="greater than zero"):
        await world.tools.set_ceiling(amount)

    assert (await world.check()).payment_ceiling is None


async def test_update_finances_saves_and_reports_the_ceiling(world: World) -> None:
    summary = await world.tools.update_finances(net_fixed_income="18000", fixed_expenses="9000")

    check = await world.check()
    assert (check.payment_ceiling, check.ceiling_source) == (Decimal("4700.00"), "finances")
    assert world.sink.events[-1].type == FINANCES_UPDATED
    lines = summary.splitlines()
    assert {"net_fixed_income: 18000", "missing: none", "payment_ceiling: 4700.00"} <= set(lines)


async def test_update_finances_rejects_a_negative_figure_naming_it(world: World) -> None:
    with pytest.raises(ToolError, match="fixed_expenses cannot be negative"):
        await world.tools.update_finances(fixed_expenses="-100")

    assert world.sink.events == []


async def test_update_finances_passes_an_engine_refusal_to_the_model(world: World) -> None:
    world.engine.assess_error = EngineError("profile.net_fixed_income: too large")

    with pytest.raises(ToolError, match="too large.*nothing was saved"):
        await world.tools.update_finances(net_fixed_income="18000", fixed_expenses="9000")

    assert (await world.check()).finances == Finances()


async def test_a_ceiling_change_asks_to_recheck_the_recommendation(world: World) -> None:
    await ready_for_recommendation(world)
    before = await world.tools.set_ceiling("2500")
    # The example fits with room, so the engine also prices it at the shorter term it finds.
    world.engine.simulations = [PRIME_SIMULATION]
    await world.tools.present_recommendation("option-1", REASONING)

    stated = await world.tools.set_ceiling("2000")
    partial = await world.tools.update_finances(net_fixed_income="18000")
    derived = await world.tools.update_finances(fixed_expenses="9000")

    assert "present_recommendation" not in before
    assert "present_recommendation" in stated
    assert "present_recommendation" not in partial
    assert "present_recommendation" in derived


async def test_save_offer_stores_engine_figures_and_emits_structured(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION]
    world.engine.calls.clear()

    summary = await world.tools.save_offer([PRIME_TRACK], lender="Bank", offer_date="2026-10-20")

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
    assert event.data["figures"] == PRIME_SIMULATION.figures.to_json()
    track, next_step = summary.splitlines()
    assert track.startswith("track 1: option_id option-1, ")
    # The model reads amounts to the shekel, as the person does.
    for figure in ("first_payment 1888", "worst_peak_payment 2039", "total_paid 90623"):
        assert figure in track
    assert "schedule" not in summary
    assert "present_recommendation" in next_step


async def test_save_offer_saves_every_track_as_an_option_of_its_own(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    world.engine.calls.clear()

    summary = await world.tools.save_offer([PRIME_TRACK, BALLOON_TRACK], "Fund", "2026-10-20")

    assert world.engine.calls == [
        ("simulate", {"tracks": [PRIME_TRACK]}),
        ("simulate", {"tracks": [BALLOON_TRACK]}),
    ]
    prime, balloon = await world.options.list(CHECK)
    assert (prime.loan, balloon.loan) == ({"tracks": [PRIME_TRACK]}, {"tracks": [BALLOON_TRACK]})
    assert {(option.source, option.lender) for option in (prime, balloon)} == {("offer", "Fund")}
    assert len(world.events_of("option.saved")) == 2
    lines = summary.splitlines()
    assert lines[0].startswith("track 1: option_id option-1, ")
    assert lines[1].startswith("track 2: option_id option-2, ")
    # Each track is compared with its sibling, which is saved by the same call.
    assert "against option option-2" in lines[0]
    assert "present_recommendation" in lines[-1]


async def test_save_offer_saves_none_of_its_tracks_when_one_is_refused(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    smaller = {**BALLOON_TRACK, "principal": "60000"}

    with pytest.raises(ToolError, match=r"tracks\[1\]: this loan borrows 60000"):
        await world.tools.save_offer([PRIME_TRACK, smaller], "Fund")

    assert await world.options.list(CHECK) == []
    assert world.events_of("option.saved") == []


async def test_save_offer_refuses_a_track_listed_twice_naming_both(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION, PRIME_SIMULATION]

    with pytest.raises(ToolError, match=r"tracks\[2\] repeats tracks\[0\]; list each track once"):
        await world.tools.save_offer([PRIME_TRACK, BALLOON_TRACK, PRIME_TRACK], "Fund")

    assert await world.options.list(CHECK) == []


async def test_save_option_needs_no_finances(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION]

    summary = await world.tools.save_option({"tracks": [PRIME_TRACK]})

    assert [option.source for option in await world.options.list(CHECK)] == ["example"]
    assert "present_recommendation" not in summary
    assert "assess" not in [name for name, _ in world.engine.calls]


async def test_a_real_offer_removes_the_examples_and_a_recommendation_naming_one(
    world: World,
) -> None:
    await ready_for_recommendation(world)
    await world.tools.present_recommendation("option-1", REASONING)
    world.sink.events.clear()
    world.engine.simulations = [PRIME_SIMULATION]

    summary = await world.tools.save_offer([PRIME_TRACK], "Bank")

    assert [option.id for option in await world.options.list(CHECK)] == ["option-3"]
    assert world.recommendations.rows == {}
    assert world.events_of(EXAMPLES_REMOVED) == [
        {"option_ids": ["option-1", "option-2"], "recommendation_removed": True}
    ]
    assert "against option" not in summary


async def test_an_offer_on_a_check_without_examples_removes_nothing(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION]

    await world.tools.save_offer([PRIME_TRACK], "Bank")

    assert world.events_of(EXAMPLES_REMOVED) == []


async def test_an_example_is_refused_once_the_check_holds_an_offer(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION]
    await world.tools.save_offer([PRIME_TRACK], "Bank")

    with pytest.raises(ToolError, match="examples are no longer saved"):
        await world.tools.save_option({"tracks": [BALLOON_TRACK]})

    assert len(await world.options.list(CHECK)) == 1


async def test_save_offer_refuses_a_principal_other_than_the_loan(world: World) -> None:
    await world.tools.set_loan(None, "60000")
    world.engine.simulations = [PRIME_SIMULATION]

    with pytest.raises(ToolError, match="80000.*60000"):
        await world.tools.save_offer([PRIME_TRACK])

    assert await world.options.list(CHECK) == []


async def test_save_offer_needs_a_loan(world: World) -> None:
    with pytest.raises(ToolError, match="set_loan"):
        await world.tools.save_offer([PRIME_TRACK])

    assert world.engine.calls == []


async def test_save_offer_engine_error_reaches_model(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulate_error = EngineError("tracks.0.term_months: must be at most 84")

    with pytest.raises(ToolError, match="tracks.0.term_months: must be at most 84"):
        await world.tools.save_offer([PRIME_TRACK], "Bank", "2026-10-20")

    assert await world.options.list(CHECK) == []


async def test_save_offer_rejects_an_offer_date_that_is_not_iso(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.calls.clear()

    with pytest.raises(ToolError, match="offer_date"):
        await world.tools.save_offer([PRIME_TRACK], None, "20/10/2026")

    assert world.engine.calls == []


async def test_an_offer_up_to_a_maximum_uses_the_first_payment_search_without_a_ceiling(
    world: World,
) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION]
    long_offer = [{**PRIME_TRACK, "term_months": 84}]

    with pytest.raises(ToolError, match="save it with term_months 24"):
        await world.tools.save_offer(long_offer, "Fund", None, 84)

    name, asked = world.engine.calls[-1]
    assert name == "propose_offer_term"
    assert asked == {"track": {**PRIME_TRACK, "term_months": 84}, "payment_limit": Decimal(1000)}
    assert await world.options.list(CHECK) == []


async def test_an_offer_up_to_a_maximum_uses_the_comfortable_search_with_a_ceiling(
    world: World,
) -> None:
    await world.tools.set_loan(None, "80000")
    await world.tools.set_ceiling("2500")
    world.engine.offer_terms = OfferTerm(term_months=48, comfortable=True)
    world.engine.simulations = [PRIME_SIMULATION]

    await world.tools.save_offer([PRIME_TRACK], "Fund", None, 84)

    name, asked = world.engine.calls[-1]
    assert name == "offer_term"
    assert asked == {
        "track": {**PRIME_TRACK, "term_months": 84},
        "payment_ceiling": Decimal(2500),
    }
    assert len(await world.options.list(CHECK)) == 1


async def test_the_engine_refusing_an_offer_term_reaches_the_model(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    await world.tools.set_ceiling("2500")
    world.engine.simulations = [PRIME_SIMULATION]
    world.engine.offer_term_error = EngineError("term_months too long")

    with pytest.raises(ToolError, match="term_months too long"):
        await world.tools.save_offer([PRIME_TRACK], "Fund", None, 84)


async def test_an_open_offer_is_priced_at_the_confirmed_term(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(72)
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION]
    world.engine.calls.clear()

    with pytest.raises(ToolError, match="save it with term_months 72"):
        await world.tools.save_offer([PRIME_TRACK], "Fund", None, 84)
    await world.tools.save_offer([{**PRIME_TRACK, "term_months": 72}], "Fund", None, 84)

    assert "propose_offer_term" not in [name for name, _ in world.engine.calls]
    (saved,) = await world.options.list(CHECK)
    assert saved.max_term_months == 84


async def test_an_offer_shorter_than_the_term_is_priced_at_its_maximum(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(72)
    world.engine.simulations = [PRIME_SIMULATION]

    with pytest.raises(ToolError, match="save it with term_months 60"):
        await world.tools.save_offer([PRIME_TRACK], "Fund", None, 60)


async def test_a_new_term_prices_the_open_offers_again_and_leaves_fixed_ones(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(48)
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION, PRIME_SIMULATION]
    await world.tools.save_offer([PRIME_TRACK], "Open", None, 84)
    await world.tools.save_offer([PRIME_TRACK], "Fixed")
    world.engine.calls.clear()
    world.sink.events.clear()

    result = await world.tools.set_term(60)

    assert "offers_repriced: option-1" in result
    assert world.engine.calls == [
        ("simulate", {"tracks": [{**PRIME_TRACK, "term_months": 60}]}),
    ]
    open_offer, fixed_offer = await world.options.list(CHECK)
    assert open_offer.loan == {"tracks": [{**PRIME_TRACK, "term_months": 60}]}
    assert fixed_offer.loan == {"tracks": [PRIME_TRACK]}
    assert [event.type for event in world.sink.events] == ["term.set", "option.saved"]


async def test_an_offer_the_engine_cannot_price_at_the_new_term_saves_nothing(
    world: World,
) -> None:
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(48)
    world.engine.simulations = [PRIME_SIMULATION]
    await world.tools.save_offer([PRIME_TRACK], "Open", None, 84)
    world.engine.simulate_error = EngineError("rate not priced")

    with pytest.raises(ToolError, match="rate not priced"):
        await world.tools.set_term(60)

    assert (await world.check()).term_months == 48


def figures_of(first_payment: str, total_paid: str) -> Simulation:
    return Simulation(
        replace(
            PRIME_SIMULATION.figures,
            first_payment=Decimal(first_payment),
            total_paid=Decimal(total_paid),
        ),
        PRIME_SIMULATION.structured,
    )


async def test_a_saved_option_is_compared_with_the_others_of_its_term(world: World) -> None:
    await world.tools.set_loan(None, "24000")
    fixed, prime = {**PRIME_TRACK, "principal": "24000"}, {**PRIME_TRACK, "principal": "24000"}
    world.engine.simulations = [figures_of("751", "27035"), figures_of("748", "26935")]
    await world.tools.save_option({"tracks": [fixed]})

    result = await world.tools.save_option({"tracks": [prime]})

    assert (
        "compared: against option option-1: first_payment 3 נמוך (זניח), "
        "total_paid 100 נמוך (במקצת)"
    ) in result


async def test_a_clear_gap_is_marked_clear_and_another_term_is_not_compared(
    world: World,
) -> None:
    await world.tools.set_loan(None, "24000")
    track = {**PRIME_TRACK, "principal": "24000"}
    world.engine.simulations = [
        figures_of("751", "27035"),
        figures_of("900", "30000"),
        figures_of("500", "29000"),
    ]
    await world.tools.save_option({"tracks": [track]})
    clear = await world.tools.save_option({"tracks": [track]})
    longer = {**track, "term_months": track["term_months"] + 12}
    other_term = await world.tools.save_option({"tracks": [longer]})

    assert "first_payment 149 גבוה (ברור), total_paid 2965 גבוה (ברור)" in clear
    assert "compared" not in other_term


async def two_offer_tracks(world: World) -> None:
    """A loan of 24,000 and one lender's two tracks for it: option-1 costs 27,035 in total and
    option-2 26,935."""
    await world.tools.set_loan(None, "24000")
    world.engine.simulations = [figures_of("751", "27035"), figures_of("748", "26935")]
    track = {**PRIME_TRACK, "principal": "24000"}
    await world.tools.save_offer([track, {**track, "prime_spread": "1"}], "Fund")


async def test_recommendation_refuses_a_dearer_option_while_a_cheaper_one_fits(
    world: World,
) -> None:
    await two_offer_tracks(world)

    with pytest.raises(ToolError, match="option option-2 costs 100 less in total"):
        await world.tools.present_recommendation("option-1", REASONING)

    assert world.events_of(RECOMMENDATION_PRESENTED) == []


async def test_a_dearer_option_is_recommended_for_what_the_person_said(world: World) -> None:
    await two_offer_tracks(world)

    await world.tools.present_recommendation(
        "option-1", REASONING, person_preference="אני שונאת הפתעות"
    )

    (presented,) = world.events_of(RECOMMENDATION_PRESENTED)
    assert presented["preferred"]["option_id"] == "option-1"


async def fitting_with_room(world: World, offered: OfferTerm, **offer: object) -> str:
    """A loan of 24,000 at 48 months under a ceiling of 3,000, its one option, an offer from Fund
    with a worst-case payment of 2,039, presented; the engine's search answers offered."""
    await world.tools.set_loan(None, "24000")
    await world.tools.set_term(48)
    await world.tools.set_ceiling("3000")
    world.engine.simulations = [figures_of("751", "27035"), figures_of("1100", "26400")]
    world.engine.offer_terms = offered
    track = {**PRIME_TRACK, "principal": "24000"}
    await world.tools.save_offer([track], "Fund", **offer)
    return await world.tools.present_recommendation("option-1", REASONING)


async def test_a_fitting_recommendation_names_its_margin_under_the_ceiling(world: World) -> None:
    result = await fitting_with_room(world, OfferTerm(term_months=48, comfortable=True))

    assert "ceiling_margin: 961 (32%)" in result.splitlines()
    assert "next_step" not in result


async def test_room_under_the_ceiling_offers_the_shortest_term_that_still_fits(
    world: World,
) -> None:
    result = await fitting_with_room(
        world, OfferTerm(term_months=24, comfortable=True), max_term_months=84
    )

    asked = [args for name, args in world.engine.calls if name == "offer_term"][-1]
    assert asked == {
        "track": {**PRIME_TRACK, "principal": "24000"},
        "payment_ceiling": Decimal(3000),
    }
    assert world.engine.calls[-1] == (
        "simulate",
        {"tracks": [{**PRIME_TRACK, "principal": "24000", "term_months": 24}]},
    )
    (next_step,) = [line for line in result.splitlines() if line.startswith("next_step")]
    assert "at 24 months" in next_step
    assert "635 less in total" in next_step
    assert "end the turn with ask_term with term_months 24" in next_step


async def test_an_offer_with_a_fixed_term_is_not_offered_a_shorter_one(world: World) -> None:
    result = await fitting_with_room(world, OfferTerm(term_months=24, comfortable=True))

    assert "offer_term" not in [name for name, _ in world.engine.calls]
    assert "next_step" not in result


async def test_a_recommendation_gives_the_named_options_current_figures(world: World) -> None:
    await ready_for_recommendation(world)

    result = await world.tools.present_recommendation(
        "option-1", REASONING, alternative_option_id="option-2"
    )

    lines = result.splitlines()
    assert any(
        line.startswith("alternative_figures: term_months 48, first_payment ") for line in lines
    )
    (preferred,) = [line for line in lines if line.startswith("preferred_figures: ")]
    assert preferred == (
        "preferred_figures: term_months 48, first_payment 1888, peak_payment 1888, "
        "worst_peak_payment 2039, worst_start 2022-04-01, worst_end 2026-03-01, balloon_due none, "
        f"total_paid 90623, rate_as_of {PRIME_SIMULATION.figures.rate_as_of}, "
        f"cpi_as_of {PRIME_SIMULATION.figures.cpi_as_of}"
    )


async def test_recommendation_needs_a_loan(world: World) -> None:
    with pytest.raises(ToolError, match="set_loan"):
        await world.tools.present_recommendation("option-1", REASONING)

    assert world.recommendations.rows == {}


async def test_recommendation_without_a_ceiling_is_unchecked(world: World) -> None:
    await ready_for_recommendation(world)

    summary = await world.tools.present_recommendation("option-1", REASONING, "option-2")

    recommendation = world.recommendations.rows[CHECK]
    assert (recommendation.preferred_option_id, recommendation.alternative_option_id) == (
        "option-1",
        "option-2",
    )
    assert recommendation.loan_amount == Decimal(80000)
    assert recommendation.payment_ceiling is None
    assert not recommendation.checked
    assert recommendation.created_at == world.clock.value
    assert world.engine.calls == []
    (event,) = world.sink.events
    assert event.type == RECOMMENDATION_PRESENTED
    assert {key: event.data[key] for key in ("loan_amount", "payment_ceiling", "checked")} == {
        "loan_amount": "80000",
        "payment_ceiling": None,
        "checked": False,
    }
    preferred = event.data["preferred"]
    assert isinstance(preferred, dict) and preferred["option_id"] == "option-1"
    assert event.data["reasoning"] == REASONING
    assert {"checked: false", "payment_ceiling: none"} <= set(summary.splitlines())


async def test_recommendation_within_a_ceiling_is_checked(world: World) -> None:
    await ready_for_recommendation(world)
    await world.tools.set_ceiling("2500")
    # The example fits with room, so the engine also prices it at the shorter term it finds.
    world.engine.simulations = [PRIME_SIMULATION]

    await world.tools.present_recommendation("option-1", REASONING, "option-2")

    recommendation = world.recommendations.rows[CHECK]
    assert recommendation.payment_ceiling == Decimal(2500)
    assert recommendation.checked


async def test_nothing_fitting_at_the_term_presents_above_the_ceiling_and_names_a_longer_term(
    world: World,
) -> None:
    await ready_for_recommendation(world)
    await world.tools.set_ceiling("1000")
    world.engine.comfortable_terms = 84
    world.engine.simulations = [
        worst_case(BALLOON_SIMULATION, "932"),
        worst_case(PRIME_SIMULATION, "1004"),
    ]

    summary = await world.tools.present_recommendation("option-2", REASONING)

    assert "option-2" in summary and "1482.61" in summary and "1000" in summary
    assert "card marks the recommendation above the ceiling" in summary
    assert "84 months" in summary
    assert "fixed track" in summary and "932" in summary
    assert "prime track" not in summary
    assert "the recommendation stands" in summary
    searched = {"principal": Decimal(80000), "payment_ceiling": Decimal(1000), "any_track": True}
    assert ("comfortable_term", searched) in world.engine.calls
    assert ("suggest", {"principal": Decimal(80000), "term_months": 84}) in world.engine.calls
    recommendation = world.recommendations.rows[CHECK]
    assert (recommendation.preferred_option_id, recommendation.payment_ceiling) == (
        "option-2",
        Decimal(1000),
    )
    assert (await world.check()).term_months == 48
    assert len(await world.options.list(CHECK)) == 2


async def offer_above_the_ceiling(world: World, offered: OfferTerm, **offer: object) -> str:
    """A real offer of 80,000 at 48 months whose worst case is above a ceiling of 1,000,
    recommended; offered answers the engine's search over the offer's terms."""
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(48)
    world.engine.simulations = [worst_case(PRIME_SIMULATION, "1004")]
    await world.tools.save_offer([PRIME_TRACK], "Bank", **offer)
    await world.tools.set_ceiling("1000")
    world.engine.offer_terms = offered
    return await world.tools.present_recommendation("option-1", REASONING)


async def test_an_offer_above_the_ceiling_names_a_longer_term_its_lender_allows(
    world: World,
) -> None:
    summary = await offer_above_the_ceiling(
        world, OfferTerm(term_months=60, comfortable=True), max_term_months=84
    )

    assert "At 60 months option option-1 fits the ceiling" in summary
    assert "comfortable_term" not in [name for name, _ in world.engine.calls]


@pytest.mark.parametrize(
    ("offered", "offer"),
    [
        (OfferTerm(term_months=48, comfortable=True), {}),
        (OfferTerm(term_months=84, comfortable=False), {"max_term_months": 84}),
    ],
)
async def test_an_offer_above_the_ceiling_at_every_term_it_allows_sends_to_the_lenders(
    world: World, offered: OfferTerm, offer: dict[str, object]
) -> None:
    summary = await offer_above_the_ceiling(world, offered, **offer)

    assert "no saved offer fits the ceiling at any term its lender allows" in summary
    assert "comfortable_term" not in [name for name, _ in world.engine.calls]


async def test_an_option_of_another_term_is_neither_recommended_nor_offered_as_fitting(
    world: World,
) -> None:
    await ready_for_recommendation(world)
    shorter = {**PRIME_TRACK, "term_months": 36}
    world.engine.simulations = [worst_case(PRIME_SIMULATION, "900")]
    await world.tools.save_option({"tracks": [shorter]})
    await world.tools.set_ceiling("1000")
    world.engine.comfortable_terms = 84

    with pytest.raises(ToolError, match="option-3 is an example for another term"):
        await world.tools.present_recommendation("option-3", REASONING)
    world.engine.simulations = [
        worst_case(BALLOON_SIMULATION, "932"),
        worst_case(PRIME_SIMULATION, "1004"),
    ]
    summary = await world.tools.present_recommendation("option-2", REASONING)

    assert "option-3" not in summary
    assert "card marks the recommendation above the ceiling" in summary


async def test_an_option_above_the_ceiling_names_a_saved_option_that_fits(world: World) -> None:
    await ready_for_recommendation(world)
    await world.tools.set_ceiling("1500")

    with pytest.raises(ToolError) as refused:
        await world.tools.present_recommendation("option-1", REASONING, "option-2")

    message = str(refused.value)
    assert "option-1" in message and "2038.63" in message
    assert "the preferred option option-1" in message
    assert "option-2 fits" in message
    assert "name an option that fits as preferred_option_id" in message
    assert "comfortable_term" not in [name for name, _ in world.engine.calls]


async def test_an_alternative_above_the_ceiling_is_refused_by_name_and_the_preferred_stands(
    world: World,
) -> None:
    await ready_for_recommendation(world)
    await world.tools.set_ceiling("1500")

    with pytest.raises(ToolError) as refused:
        await world.tools.present_recommendation("option-2", REASONING, "option-1")

    message = str(refused.value)
    assert "the alternative option option-1" in message and "2038.63" in message
    assert "the preferred option option-2" not in message
    assert "with preferred_option_id option-2 and without alternative_option_id" in message
    assert "or with an alternative that fits" not in message
    assert world.recommendations.rows == {}


async def test_nothing_fits_even_at_84_months_names_the_largest_loan(world: World) -> None:
    await ready_for_recommendation(world)
    await world.tools.set_ceiling("1000")
    world.engine.comfortable_terms = None
    world.engine.largest_loans = Decimal(45000)

    message = await world.tools.present_recommendation("option-2", REASONING)

    assert "no term up to 84 months" in message
    assert "45000" in message and "48 months" in message
    assert "borrow less or put in more own capital" in message
    assert ("largest_loan", {"payment_ceiling": Decimal(1000), "term_months": 48}) in (
        world.engine.calls
    )
    assert CHECK in world.recommendations.rows


async def test_a_ceiling_too_low_for_any_loan_names_none(world: World) -> None:
    await ready_for_recommendation(world)
    await world.tools.set_ceiling("200")
    world.engine.comfortable_terms = None
    world.engine.largest_loans = None

    message = await world.tools.present_recommendation("option-2", REASONING)

    assert "no loan the simulator prices fits" in message
    assert "largest loan" not in message
    assert CHECK in world.recommendations.rows


async def test_expenses_above_income_give_a_zero_ceiling(world: World) -> None:
    await ready_for_recommendation(world)
    world.engine.bounds = replace(
        ASSESSED_BOUNDS, payment_ceiling=Decimal(0), reasons=("no_room_for_payment",)
    )

    await world.tools.update_finances(net_fixed_income="5000", fixed_expenses="6000")

    check = await world.check()
    assert (check.payment_ceiling, check.ceiling_source) == (Decimal(0), "finances")
    for option_id in ("option-1", "option-2"):
        summary = await world.tools.present_recommendation(option_id, REASONING)
        assert "no loan the simulator prices fits" in summary
    # The engine's searches take a positive ceiling only.
    searched = {"comfortable_term", "largest_loan", "suggest"}
    assert searched.isdisjoint(name for name, _ in world.engine.calls)


async def test_a_zero_ceiling_keeps_an_open_offer_at_its_longest_term(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    await world.checks.set_ceiling(CHECK, Decimal(0), "finances")
    world.engine.simulations = [PRIME_SIMULATION]

    with pytest.raises(ToolError, match="save it with term_months 84"):
        await world.tools.save_offer([PRIME_TRACK], "Fund", None, 84)

    assert "offer_term" not in [name for name, _ in world.engine.calls]


async def test_recommendation_refuses_an_option_of_another_amount(world: World) -> None:
    await ready_for_recommendation(world)

    await world.tools.set_loan(None, "90000")

    with pytest.raises(ToolError, match="option-2 borrows 80000.*90000"):
        await world.tools.present_recommendation("option-2", REASONING)
    assert world.recommendations.rows == {}


async def test_changing_the_amount_after_a_recommendation_tells_the_model(world: World) -> None:
    await ready_for_recommendation(world)
    await world.tools.present_recommendation("option-1", REASONING)

    changed = await world.tools.set_loan(None, "90000")
    same = await world.tools.set_loan(None, "80000")

    assert "recommendation is for 80000" in changed
    assert "recommendation is for" not in same


async def test_balloon_option_judged_on_recurring_payment(world: World) -> None:
    await ready_for_recommendation(world)
    await world.tools.set_ceiling("1550")
    balloon = replace(BALLOON_SIMULATION.figures, balloon_due=Decimal(10000))
    world.options.rows[CHECK][1] = replace(world.options.rows[CHECK][1], summary=balloon)
    # The example fits with room, so the engine also prices it at the shorter term it finds.
    world.engine.simulations = [BALLOON_SIMULATION]

    await world.tools.present_recommendation("option-2", REASONING)

    assert world.recommendations.rows[CHECK].preferred_option_id == "option-2"


async def test_recommendation_refused_for_unknown_option(world: World) -> None:
    await ready_for_recommendation(world)

    with pytest.raises(ToolError, match="alternative_option_id.*option-9"):
        await world.tools.present_recommendation("option-2", REASONING, "option-9")


async def test_recommendation_refused_when_reasoning_names_an_option_id(world: World) -> None:
    await ready_for_recommendation(world)

    with pytest.raises(ToolError, match="names an option by its id"):
        await world.tools.present_recommendation("option-2", "ממליץ על option-2 כי הוא זול")

    assert world.recommendations.rows == {}


async def test_recommendation_reasoning_with_an_english_word_is_refused(world: World) -> None:
    await ready_for_recommendation(world)

    with pytest.raises(ToolError, match="reasoning has the English word 'prime'"):
        await world.tools.present_recommendation("option-2", "מסלול prime זול יותר")

    assert world.recommendations.rows == {}


async def test_ask_emits_the_question_and_ends_with_the_fixed_result(world: World) -> None:
    question = {"field": "payment_ceiling", "text": None, "choices": None, "offer_clone": False}

    result = await world.tools.ask(question, "כדי לבדוק את ההמלצה")

    assert result == ASKED_RESULT
    assert world.events_of(QUESTION_ASKED) == [
        {"question": question, "lead_in": "כדי לבדוק את ההמלצה"}
    ]


@pytest.mark.parametrize(
    ("field", "known"),
    [
        ("net_fixed_income", "12000"),
        ("payment_ceiling", "1500"),
        ("amount", "60000"),
        ("purpose", "רכב"),
    ],
)
async def test_ask_refuses_a_known_field_naming_its_value(
    world: World, field: str, known: str
) -> None:
    await world.tools.set_loan("רכב", "60000")
    await world.tools.set_ceiling("1500")
    await world.tools.update_finances(net_fixed_income="12000")
    world.sink.events.clear()

    with pytest.raises(ToolError, match=f"{field} is already known: {known}"):
        await world.tools.ask(
            {"field": field, "text": None, "choices": None, "offer_clone": False}, None
        )

    assert world.sink.events == []


async def test_ask_allows_an_unknown_field_and_a_free_question(world: World) -> None:
    await world.tools.set_loan(None, "60000")

    for field in ("purpose", "own_capital", "fixed_expenses", "payment_ceiling"):
        await world.tools.ask(
            {"field": field, "text": None, "choices": None, "offer_clone": False}, None
        )
    await world.tools.ask(
        {"field": None, "text": "חדש או משומש?", "choices": ["חדש", "משומש"], "offer_clone": False},
        None,
    )

    assert len(world.events_of(QUESTION_ASKED)) == 5


@pytest.mark.parametrize(
    ("question", "lead_in"),
    [
        ({"text": "איזו הלוואה לקחת?", "choices": None}, "ההלוואה ש-set_loan שמר"),
        ({"text": "how much?", "choices": None}, None),
        ({"text": "איזו הלוואה?", "choices": ["הלוואה של 110,000 ₪", "loan"]}, None),
    ],
)
async def test_ask_refuses_an_english_word_the_person_would_see(
    world: World, question: dict[str, object], lead_in: str | None
) -> None:
    with pytest.raises(ToolError, match="reads Hebrew only"):
        await world.tools.ask({**question, "field": None, "offer_clone": False}, lead_in)

    assert world.sink.events == []


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


async def test_save_option_refuses_an_option_already_saved_with_the_same_figures(
    world: World,
) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION, PRIME_SIMULATION]
    await world.tools.save_offer([PRIME_TRACK], "Fund", "2026-10-20")

    with pytest.raises(ToolError, match="already saved as option option-1"):
        await world.tools.save_offer([PRIME_TRACK], "Fund", "2026-10-20")
    await world.tools.save_offer([PRIME_TRACK], "Bank", "2026-10-20")

    assert [option.lender for option in await world.options.list(CHECK)] == ["Fund", "Bank"]
