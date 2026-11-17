"""The agent's own tools save the loan, its term, its ceiling and the finances on the check, and
refuse a recommendation that breaks the rules, with messages the model can act on: every named
option borrows the loan amount, and with a ceiling every one fits it. read_offer saves an offer
that one of the engine's readings fits, and keeps an offer that several readings fit, or that is
quoted for less than the loan, awaiting the person's answer."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from fakes import (
    ASSESSED_BOUNDS,
    BALLOON_SIMULATION,
    LEUMI_READINGS,
    NOW,
    PRIME_SIMULATION,
    Clock,
    FakeLoanEngine,
    Ids,
    InMemoryAwaitingOfferRepository,
    InMemoryCheckRepository,
    InMemoryOptionRepository,
    InMemoryRecommendationRepository,
    RecordingSink,
    reading,
    readings_of,
)
from loan_agent.application.check_tools import (
    ASKED_RESULT,
    READING_ON_SCREEN,
    CheckTools,
    ToolDeps,
    ToolError,
)
from loan_agent.domain.errors import AwaitingOfferNotFoundError
from loan_agent.domain.models import Check, Finances, LoanRequest, Option
from loan_agent.ports.engine import (
    EngineError,
    OfferTerm,
    ProposedTerm,
    Simulation,
)
from loan_agent.ports.events import (
    CEILING_SET,
    CHART_SHOWN,
    EXAMPLES_REMOVED,
    FINANCES_UPDATED,
    LOAN_SET,
    OFFER_AWAITING,
    OFFER_DROPPED,
    OFFER_IDENTIFIED,
    OFFER_SETTLED,
    OFFER_UNRECOGNIZED,
    OPTION_SAVED,
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
    awaiting: InMemoryAwaitingOfferRepository
    recommendations: InMemoryRecommendationRepository
    engine: FakeLoanEngine
    sink: RecordingSink
    new_id: Ids
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
    awaiting = InMemoryAwaitingOfferRepository()
    recommendations = InMemoryRecommendationRepository()
    engine = FakeLoanEngine()
    sink = RecordingSink()
    await checks.add(Check(CHECK, PERSON, NOW, None, None, None, None, Finances()))
    new_id = Ids("option")
    deps = ToolDeps(
        checks=checks,
        options=options,
        awaiting=awaiting,
        recommendations=recommendations,
        engine=engine,
        sink=sink,
        clock=clock,
        new_id=new_id,
    )
    return World(
        clock,
        checks,
        options,
        awaiting,
        recommendations,
        engine,
        sink,
        new_id,
        CheckTools(PERSON, CHECK, deps),
    )


async def add_example(world: World, track: Mapping[str, object]) -> None:
    """Puts an example of the track among the check's options, with the figures of the engine's
    next simulation, as save_examples leaves each of its own; for a test that needs examples of
    tracks it chooses."""
    simulation = world.engine.simulations.pop(0)
    await world.options.add(
        Option(
            id=world.new_id(),
            check_id=CHECK,
            loan={"tracks": [track]},
            source="example",
            lender=None,
            offer_date=None,
            max_term_months=None,
            summary=simulation.figures,
            created_at=world.clock.value,
        )
    )


async def ready_for_recommendation(world: World) -> None:
    """A loan of 80,000 at 48 months and two examples of it, before any real offer: the prime
    track, the cheaper in total, and the balloon track."""
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(48)
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    await add_example(world, PRIME_TRACK)
    await add_example(world, BALLOON_TRACK)
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


async def test_ask_term_proposes_a_cars_term_from_the_first_payment_target(world: World) -> None:
    await world.tools.set_loan("רכב", "60000")
    world.engine.proposed = ProposedTerm(term_months=66, first_payment=Decimal("998.40"))
    world.engine.calls.clear()

    result = await world.tools.ask_term(None)

    assert result == ASKED_RESULT
    assert world.engine.calls == [
        ("propose_term", {"principal": Decimal(60000), "payment_limit": Decimal(1000)})
    ]
    assert world.events_of(QUESTION_ASKED) == [
        {
            "question": {
                "kind": "term",
                "term_months": 66,
                "first_payment": "998.40",
                "basis": {"kind": "first_payment_target", "amount": "1000", "fits": True},
            },
            "lead_in": None,
        }
    ]


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
            "question": {
                "kind": "term",
                "term_months": 84,
                "first_payment": "1554.00",
                "basis": {"kind": "first_payment_target", "amount": "1000", "fits": False},
            },
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
    assert asked["question"]["basis"] == {
        "kind": "ceiling",
        "amount": "1000",
        "fits": found is not None,
    }


async def test_ask_term_shows_the_term_the_person_typed(world: World) -> None:
    await world.tools.set_loan(None, "100000")
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    world.engine.calls.clear()

    await world.tools.ask_term(36)

    assert world.engine.calls[0] == (
        "suggest",
        {"principal": Decimal(100000), "term_months": 36},
    )
    (asked,) = world.events_of(QUESTION_ASKED)
    assert isinstance(asked, dict) and asked["question"]["basis"] == {"kind": "typed"}


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
    assert "price interest_cost 10623 on 80000; rate_today 6.25%, below " in track
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


THIRD_SIMULATION = worst_case(PRIME_SIMULATION, "2100")


async def examples_ready(world: World) -> None:
    """A loan of 80,000 at 48 months with no option yet, and the engine's three simulations."""
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(48)
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION, THIRD_SIMULATION]
    world.sink.events.clear()


async def test_save_examples_saves_every_track_the_engine_suggests_in_one_call(
    world: World,
) -> None:
    await examples_ready(world)

    summary = await world.tools.save_examples()

    options = await world.options.list(CHECK)
    assert [option.source for option in options] == ["example"] * 3
    suggested = await world.engine.suggest(Decimal(80000), 48)
    assert [option.loan for option in options] == [{"tracks": [track]} for track in suggested]
    assert len(world.events_of(OPTION_SAVED)) == 3
    first, second, third = summary.splitlines()
    assert first.startswith("example 1: track fixed 7.9, not linked, option_id option-1, ")
    assert second.startswith("example 2: track prime + 2.9, not linked, option_id option-2, ")
    assert third.startswith("example 3: track fixed 4, linked, option_id option-3, ")
    assert "assess" not in [name for name, _ in world.engine.calls]


async def test_save_examples_saves_none_when_the_engine_refuses_one(world: World) -> None:
    await examples_ready(world)
    priced = world.engine.simulate

    async def third_refused(loan: Mapping[str, object]) -> Simulation:
        if len(world.engine.simulations) == 1:
            raise EngineError("no rate is published")
        return await priced(loan)

    world.engine.simulate = third_refused  # type: ignore[method-assign]

    with pytest.raises(ToolError, match="example 3: .*no rate is published.*no example"):
        await world.tools.save_examples()

    assert await world.options.list(CHECK) == []
    assert world.events_of(OPTION_SAVED) == []


async def test_save_examples_keeps_an_example_already_saved_and_adds_the_missing(
    world: World,
) -> None:
    await examples_ready(world)
    (fixed, _, _) = await world.engine.suggest(Decimal(80000), 48)
    world.engine.simulations.insert(0, PRIME_SIMULATION)
    await add_example(world, fixed)

    summary = await world.tools.save_examples()

    assert [option.id for option in await world.options.list(CHECK)] == [
        "option-1",
        "option-3",
        "option-4",
    ]
    assert len(world.events_of(OPTION_SAVED)) == 2
    assert summary.splitlines()[0].startswith("example 1: track fixed 7.9, not linked, option_id ")
    assert "option_id option-1, " in summary.splitlines()[0]


async def test_save_examples_needs_a_confirmed_term(world: World) -> None:
    await world.tools.set_loan(None, "80000")

    with pytest.raises(ToolError, match="ask_term"):
        await world.tools.save_examples()

    assert await world.options.list(CHECK) == []


async def test_save_examples_passes_on_the_engines_refusal_to_suggest(world: World) -> None:
    await examples_ready(world)
    world.engine.suggest_error = EngineError("no rate is published")

    with pytest.raises(ToolError, match="no rate is published"):
        await world.tools.save_examples()


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

    await world.tools.set_term(48)

    with pytest.raises(ToolError, match="examples are no longer saved"):
        await world.tools.save_examples()

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
    await world.tools.save_offer([fixed], "Fund")

    result = await world.tools.save_offer([prime], "Bank")

    assert (
        "compared against option option-1: first_payment 3 נמוך (זניח), total_paid 100 נמוך (במקצת)"
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
    await world.tools.save_offer([track], "Fund")
    clear = await world.tools.save_offer([track], "Bank")
    longer = {**track, "term_months": track["term_months"] + 12}
    other_term = await world.tools.save_offer([longer], "Agency")

    assert "first_payment 149 גבוה (ברור), total_paid 2965 גבוה (ברור)" in clear
    assert "compared against" not in other_term


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

    assert "preferred_ceiling_margin: 961 (32%)" in result.splitlines()
    assert "alternative_ceiling_margin" not in result
    assert "next_step" not in result


async def test_an_option_whose_payment_never_changes_gives_no_historical_figures(
    world: World,
) -> None:
    """A fixed unlinked track has no worst case in history; its figures say the payment never
    changes and leave the three historical figures out, so no reply has a period to describe."""
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(48)
    steady = replace(
        PRIME_SIMULATION.figures, worst_peak_payment=None, worst_start=None, worst_end=None
    )
    world.engine.simulations = [replace(PRIME_SIMULATION, figures=steady)]
    await add_example(world, PRIME_TRACK)

    result = await world.tools.present_recommendation("option-1", REASONING)

    (figures,) = [line for line in result.splitlines() if line.startswith("preferred_figures: ")]
    assert "payment_changes never" in figures
    assert "worst" not in figures


async def test_a_fitting_recommendation_names_the_margin_of_its_alternative_too(
    world: World,
) -> None:
    await world.tools.set_loan(None, "24000")
    await world.tools.set_term(48)
    await world.tools.set_ceiling("3000")
    dearer = figures_of("760", "27400")
    world.engine.simulations = [
        figures_of("751", "27035"),
        Simulation(replace(dearer.figures, worst_peak_payment=Decimal(2850)), dearer.structured),
    ]
    track = {**PRIME_TRACK, "principal": "24000"}
    await world.tools.save_offer([track, {**track, "prime_spread": "2"}], "Fund")

    result = await world.tools.present_recommendation("option-1", REASONING, "option-2")

    lines = result.splitlines()
    assert "preferred_ceiling_margin: 961 (32%)" in lines
    assert "alternative_ceiling_margin: 150 (5%)" in lines


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
    (preferred_price,) = [line for line in lines if line.startswith("preferred_price: ")]
    assert preferred_price == (
        "preferred_price: interest_cost 10623 on 80000; rate_today 6.25%, below the average "
        "bank rate on consumer loans of 7.9% as of 2026-08"
    )
    (alternative_price,) = [line for line in lines if line.startswith("alternative_price: ")]
    assert alternative_price == (
        "alternative_price: interest_cost 16050 on 80000, the CPI's rise included; rate_today "
        "4.9% on top of the CPI, not comparable with the unlinked average"
    )
    assert not any(line.startswith("only_option: ") for line in lines)


async def test_one_real_offer_alone_is_evaluated_with_its_price_not_recommended(
    world: World,
) -> None:
    await world.tools.set_loan(None, "80000")
    await world.tools.set_term(48)
    world.engine.simulations = [PRIME_SIMULATION]
    await world.tools.save_offer([PRIME_TRACK], lender="לאומי")

    result = await world.tools.present_recommendation("option-1", REASONING)

    lines = result.splitlines()
    assert "preferred_price: interest_cost 10623 on 80000; rate_today 6.25%, below " in "\n".join(
        lines
    )
    (only,) = [line for line in lines if line.startswith("only_option: ")]
    for words in ("only offer", "never call it preferred or recommended", "interest_cost"):
        assert words in only
    assert "another offer" in only


async def test_an_option_saved_before_the_engine_priced_rates_gives_only_its_interest_cost(
    world: World,
) -> None:
    await ready_for_recommendation(world)
    (prime, _) = await world.options.list(CHECK)
    await world.options.replace(replace(prime, summary=replace(prime.summary, price=None)))

    result = await world.tools.present_recommendation("option-1", REASONING, "option-2")

    assert "preferred_price: interest_cost 10623 on 80000\n" in result


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
    await add_example(world, shorter)
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


async def test_save_offer_refuses_an_offer_already_saved_with_the_same_figures(
    world: World,
) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION, PRIME_SIMULATION]
    await world.tools.save_offer([PRIME_TRACK], "Fund", "2026-10-20")

    with pytest.raises(ToolError, match="already saved as option option-1"):
        await world.tools.save_offer([PRIME_TRACK], "Fund", "2026-10-20")
    await world.tools.save_offer([PRIME_TRACK], "Bank", "2026-10-20")

    assert [option.lender for option in await world.options.list(CHECK)] == ["Fund", "Bank"]


async def test_a_lender_misspelled_by_one_letter_is_the_same_offer(world: World) -> None:
    await world.tools.set_loan(None, "80000")
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION, PRIME_SIMULATION]
    await world.tools.save_offer([PRIME_TRACK], "סוכנות אוויס רכבים", "2026-10-20")

    with pytest.raises(ToolError, match="already saved as option option-1"):
        await world.tools.save_offer([PRIME_TRACK], "סוכנות אווויס רכבים", "2026-10-20")
    with pytest.raises(ToolError, match="already saved as option option-1"):
        await world.tools.save_offer([PRIME_TRACK], "סוכנות אויס רכבים", "2026-10-20")


# Max's "prime 6.45", 20,000 over 24 months at 934 a month.
MAX_READINGS = readings_of(
    reading("prime_margin", "6.45", "933.85", "11.20", "20000", 24),
    reading("prime_total", "1.7", "889.37", "6.45", "20000", 24),
    reading("fixed_unlinked", "6.45", "889.37", "6.45", "20000", 24),
    reading("fixed_linked", "6.45", "890.80", "6.45", "20000", 24),
    payment_rate="11.17",
)


async def car_loan(world: World) -> None:
    await world.tools.set_loan("רכב", "45000")
    await world.tools.set_term(60)
    world.sink.events.clear()
    world.engine.calls.clear()


async def avis_awaiting(world: World) -> str:
    """Avis quotes 969 a month with no number and no type, read by the engine's captured
    readings."""
    await car_loan(world)
    result = await world.tools.read_offer("אוויס", "45000", 60, None, "969", [], None)
    assert result == READING_ON_SCREEN
    (offer,) = await world.awaiting.list(CHECK)
    return offer.id


def offer_readings_calls(world: World) -> list[object]:
    return [args for name, args in world.engine.calls if name == "offer_readings"]


async def test_leumis_offer_is_identified_as_prime_plus_6(world: World) -> None:
    await car_loan(world)
    world.engine.readings = LEUMI_READINGS
    world.engine.simulations = [PRIME_SIMULATION]

    result = await world.tools.read_offer(
        "לאומי", "45000", 60, "6", "972", ["prime", "fixed"], None
    )

    (option,) = await world.options.list(CHECK)
    (track,) = option.loan["tracks"]  # type: ignore[attr-defined]
    assert (option.source, option.lender) == ("offer", "לאומי")
    assert (track["rate_kind"], track["prime_spread"]) == ("prime", "6")
    assert track["principal"] == "45000"
    (identified,) = world.events_of(OFFER_IDENTIFIED)
    assert identified["option_id"] == option.id  # type: ignore[index]
    assert identified["reading"]["total_rate"] == "10.75"  # type: ignore[index]
    assert identified["monthly_payment"] == "972"  # type: ignore[index]
    (asked,) = offer_readings_calls(world)
    assert asked["prime_total"] is True  # type: ignore[index]
    assert "present_recommendation" in result
    assert await world.awaiting.list(CHECK) == []


async def test_an_offer_quoted_for_more_is_identified_on_its_own_amount_and_saved_on_the_checks(
    world: World,
) -> None:
    await world.tools.set_loan("רכב", "15000")
    world.sink.events.clear()
    world.engine.readings = MAX_READINGS
    world.engine.simulations = [PRIME_SIMULATION]

    await world.tools.read_offer("מקס", "20000", 24, "6.45", "934", ["prime"], None)

    (asked,) = offer_readings_calls(world)
    assert (asked["principal"], asked["term_months"]) == (Decimal(20000), 24)  # type: ignore[index]
    (option,) = await world.options.list(CHECK)
    (track,) = option.loan["tracks"]  # type: ignore[attr-defined]
    assert (track["principal"], track["term_months"]) == ("15000", 24)
    (identified,) = world.events_of(OFFER_IDENTIFIED)
    assert {
        key: identified[key]  # type: ignore[index]
        for key in ("quoted_amount", "loan_amount", "lender", "prime", "rate_as_of")
    } == {
        "quoted_amount": "20000",
        "loan_amount": "15000",
        "lender": "מקס",
        "prime": "4.75",
        "rate_as_of": "2026-11-15",
    }
    assert identified["reading"]["total_rate"] == "11.20"  # type: ignore[index]
    assert (await world.check()).payment_ceiling is None


async def max_short(world: World) -> str:
    """Max quotes 20,000 at prime 6.45 and 934 a month, on a check of 45,000: identified, and
    short of the loan."""
    await car_loan(world)
    world.engine.readings = MAX_READINGS
    result = await world.tools.read_offer("מקס", "20000", 24, "6.45", "934", ["prime"], None)
    assert result == READING_ON_SCREEN
    (offer,) = await world.awaiting.list(CHECK)
    return offer.id


async def test_an_identified_offer_quoted_for_less_awaits_the_lenders_answer_on_the_amount(
    world: World,
) -> None:
    awaiting_id = await max_short(world)

    assert await world.options.list(CHECK) == []
    assert world.events_of(OFFER_IDENTIFIED) == []
    (offer,) = await world.awaiting.list(CHECK)
    assert (offer.amount, offer.term_months) == (Decimal(20000), 24)
    assert [held.kind for held in offer.readings] == ["prime_margin"]
    (event,) = world.events_of(OFFER_AWAITING)
    assert event["awaiting_id"] == awaiting_id  # type: ignore[index]
    assert event["amount"] == "20000"  # type: ignore[index]
    assert event["identified"] is True  # type: ignore[index]


async def test_an_open_offer_quoted_for_less_awaits_with_its_readings(world: World) -> None:
    await car_loan(world)
    world.engine.readings = MAX_READINGS

    await world.tools.read_offer("מקס", "20000", 24, None, "934", [], None)

    (offer,) = await world.awaiting.list(CHECK)
    assert len(offer.readings) == 4
    (event,) = world.events_of(OFFER_AWAITING)
    assert event["identified"] is False  # type: ignore[index]


async def test_the_lender_lending_the_loan_amount_saves_the_offer_at_it(world: World) -> None:
    awaiting_id = await max_short(world)
    (offer,) = await world.awaiting.list(CHECK)
    world.engine.simulations = [PRIME_SIMULATION]
    world.sink.events.clear()

    result = await world.tools.answer_offer_amount(awaiting_id, True, None)

    (option,) = await world.options.list(CHECK)
    (track,) = option.loan["tracks"]  # type: ignore[attr-defined]
    assert (track["principal"], track["term_months"]) == ("45000", 24)
    assert (track["rate_kind"], track["prime_spread"]) == ("prime", "6.45")
    assert (option.source, option.lender) == ("offer", "מקס")
    assert await world.awaiting.list(CHECK) == []
    assert world.events_of(OFFER_SETTLED) == [
        {
            "awaiting_id": awaiting_id,
            "kind": "prime_margin",
            "reading": offer.readings[0].to_json(),
        }
    ]
    assert "present_recommendation" in result


async def test_the_lender_not_lending_the_loan_amount_drops_the_offer(world: World) -> None:
    awaiting_id = await max_short(world)
    world.sink.events.clear()

    result = await world.tools.answer_offer_amount(awaiting_id, False, None)

    assert await world.awaiting.list(CHECK) == []
    assert await world.options.list(CHECK) == []
    assert world.events_of(OFFER_DROPPED) == [
        {
            "awaiting_id": awaiting_id,
            "lender": "מקס",
            "quoted_amount": "20000",
            "loan_amount": "45000",
        }
    ]
    assert "do not repeat" in result


async def test_lending_the_loan_amount_on_a_card_of_readings_takes_the_chosen_one(
    world: World,
) -> None:
    await car_loan(world)
    world.engine.readings = MAX_READINGS
    await world.tools.read_offer("מקס", "20000", 24, None, "934", [], None)
    (offer,) = await world.awaiting.list(CHECK)
    world.engine.simulations = [PRIME_SIMULATION]

    with pytest.raises(ToolError, match="prime_margin, prime_total"):
        await world.tools.answer_offer_amount(offer.id, True, None)
    with pytest.raises(ToolError, match="no balloon reading"):
        await world.tools.answer_amount(offer.id, True, "balloon")  # type: ignore[arg-type]
    await world.tools.answer_amount(offer.id, True, "fixed_linked")

    (option,) = await world.options.list(CHECK)
    (track,) = option.loan["tracks"]  # type: ignore[attr-defined]
    assert (track["principal"], track["cpi_linked"]) == ("45000", True)
    (settled,) = world.events_of(OFFER_SETTLED)
    assert settled["kind"] == "fixed_linked"  # type: ignore[index]


async def test_the_amount_question_is_only_for_an_offer_quoted_for_less(world: World) -> None:
    awaiting_id = await avis_awaiting(world)

    with pytest.raises(ToolError, match="no amount question"):
        await world.tools.answer_amount(awaiting_id, False, None)
    with pytest.raises(AwaitingOfferNotFoundError):
        await world.tools.answer_amount("nope", False, None)
    with pytest.raises(ToolError, match="no awaiting offer 'nope'"):
        await world.tools.answer_offer_amount("nope", False, None)

    assert len(await world.awaiting.list(CHECK)) == 1


async def test_a_reading_confirmed_without_the_amount_answer_is_refused(world: World) -> None:
    awaiting_id = await max_short(world)

    with pytest.raises(ToolError, match="answer its amount question"):
        await world.tools.confirm_reading(awaiting_id, "prime_margin")

    assert await world.options.list(CHECK) == []
    assert len(await world.awaiting.list(CHECK)) == 1


async def test_aviss_offer_awaits_with_three_readings(world: World) -> None:
    awaiting_id = await avis_awaiting(world)

    assert await world.options.list(CHECK) == []
    (event,) = world.events_of(OFFER_AWAITING)
    assert event == {
        "awaiting_id": awaiting_id,
        "lender": "אוויס",
        "amount": "45000",
        "term_months": 60,
        "monthly_payment": "969",
        "payment_rate": "10.58",
        "type_words": [],
        "readings": [reading.to_json() for reading in world.engine.readings.readings],
        "likely": None,
        "identified": False,
        "prime": "4.75",
        "rate_as_of": "2026-10-20",
    }
    assert [r["kind"] for r in event["readings"]] == [  # type: ignore[index]
        "fixed_unlinked",
        "prime_margin",
        "fixed_linked",
    ]


async def test_a_later_word_moves_the_likely_reading_and_confirms_nothing(world: World) -> None:
    awaiting_id = await avis_awaiting(world)

    result = await world.tools.read_offer(None, None, None, None, None, ["fixed"], awaiting_id)

    assert result == READING_ON_SCREEN
    (offer,) = await world.awaiting.list(CHECK)
    assert (offer.id, len(offer.readings), offer.likely) == (awaiting_id, 3, "fixed_unlinked")
    assert (offer.lender, offer.monthly_payment) == ("אוויס", Decimal(969))
    events = world.events_of(OFFER_AWAITING)
    assert [event["awaiting_id"] for event in events] == [awaiting_id] * 2  # type: ignore[index]
    assert await world.options.list(CHECK) == []


async def test_an_awaiting_offer_removes_the_examples(world: World) -> None:
    await car_loan(world)
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    of_the_check = {"principal": "45000", "term_months": 60}
    await add_example(world, {**PRIME_TRACK, **of_the_check})
    await add_example(world, {**BALLOON_TRACK, **of_the_check})
    await world.tools.present_recommendation("option-1", REASONING)

    await world.tools.read_offer("אוויס", "45000", 60, None, "969", [], None)

    assert await world.options.list(CHECK) == []
    assert world.recommendations.rows == {}
    assert world.events_of(EXAMPLES_REMOVED) == [
        {"option_ids": ["option-1", "option-2"], "recommendation_removed": True}
    ]


async def test_an_example_is_refused_while_an_offer_awaits(world: World) -> None:
    await avis_awaiting(world)
    world.engine.simulations = [PRIME_SIMULATION]

    with pytest.raises(ToolError, match="examples are no longer saved") as refused:
        await world.tools.save_examples()

    assert "tell the person" in str(refused.value)
    assert await world.options.list(CHECK) == []


async def test_a_number_that_fits_nothing_saves_nothing(world: World) -> None:
    await car_loan(world)
    world.engine.readings = LEUMI_READINGS

    result = await world.tools.read_offer("לאומי", "45000", 60, "5", "1100", [], None)

    assert result == READING_ON_SCREEN
    assert world.events_of(OFFER_UNRECOGNIZED) == [{"lender": "לאומי"}]
    assert await world.options.list(CHECK) == []
    assert await world.awaiting.list(CHECK) == []


async def test_an_unrecognized_number_leaves_an_awaiting_offer_as_it_is(world: World) -> None:
    awaiting_id = await avis_awaiting(world)
    (before,) = await world.awaiting.list(CHECK)
    world.engine.readings = readings_of(
        reading("prime_margin", "5", "1167.74", "9.75", "45000", 60),
        reading("fixed_unlinked", "5", "849.21", "5", "45000", 60),
        payment_rate="10.58",
    )

    await world.tools.read_offer(None, None, None, "5", None, [], awaiting_id)
    world.engine.readings = readings_of(payment_rate="10.58")
    await world.tools.read_offer(None, None, None, "5", None, [], awaiting_id)

    assert await world.awaiting.list(CHECK) == [before]
    assert world.events_of(OFFER_UNRECOGNIZED) == [{"lender": "אוויס"}] * 2


async def test_an_awaiting_offer_is_identified_once_its_number_is_known(world: World) -> None:
    awaiting_id = await avis_awaiting(world)
    world.engine.readings = readings_of(
        reading("prime_margin", "10.58", "1215.40", "15.33", "45000", 60),
        reading("fixed_unlinked", "10.58", "969.01", "10.58", "45000", 60),
        payment_rate="10.58",
    )
    world.engine.simulations = [PRIME_SIMULATION]
    world.sink.events.clear()

    await world.tools.read_offer(None, None, None, "10.58", None, [], awaiting_id)

    (option,) = await world.options.list(CHECK)
    assert option.lender == "אוויס"
    assert await world.awaiting.list(CHECK) == []
    offer_events = [event.type for event in world.sink.events if event.type.startswith("offer.")]
    assert offer_events == [OFFER_SETTLED, OFFER_IDENTIFIED]
    fixed = reading("fixed_unlinked", "10.58", "969.01", "10.58", "45000", 60)
    assert world.events_of(OFFER_SETTLED) == [
        {"awaiting_id": awaiting_id, "kind": "fixed_unlinked", "reading": fixed.to_json()}
    ]


async def test_an_awaiting_offer_settles_by_a_reading_its_card_does_not_hold(
    world: World,
) -> None:
    awaiting_id = await avis_awaiting(world)
    (before,) = await world.awaiting.list(CHECK)
    assert "prime_total" not in {held.kind for held in before.readings}
    total = reading("prime_total", "5.83", "969.20", "10.58", "45000", 60)
    world.engine.readings = readings_of(
        total,
        reading("fixed_unlinked", "10.58", "1050.00", "10.58", "45000", 60),
        payment_rate="10.58",
    )
    world.engine.simulations = [PRIME_SIMULATION]

    await world.tools.read_offer(None, None, None, "5.83", None, ["prime"], awaiting_id)

    assert world.events_of(OFFER_SETTLED) == [
        {"awaiting_id": awaiting_id, "kind": "prime_total", "reading": total.to_json()}
    ]


async def test_the_same_offer_described_again_names_the_awaiting_one(world: World) -> None:
    awaiting_id = await avis_awaiting(world)

    with pytest.raises(ToolError, match=f"awaiting_id {awaiting_id}"):
        await world.tools.read_offer("אוויס", None, None, None, "969", ["fixed"], None)

    assert len(await world.awaiting.list(CHECK)) == 1


async def test_read_offer_refusals_name_what_to_do(world: World) -> None:
    await world.tools.set_loan("רכב", "45000")

    with pytest.raises(ToolError, match="who made the offer"):
        await world.tools.read_offer(None, None, 60, "6", "972", [], None)
    with pytest.raises(ToolError, match="ask_offer"):
        await world.tools.read_offer("לאומי", None, 60, None, None, ["prime"], None)
    with pytest.raises(ToolError, match="number of months"):
        await world.tools.read_offer("לאומי", None, None, "6", "972", [], None)
    with pytest.raises(ToolError, match="no awaiting offer 'nope'"):
        await world.tools.read_offer(None, None, 60, "6", None, [], "nope")
    world.engine.readings_error = EngineError("principal must be at least 10000")
    with pytest.raises(ToolError, match="principal must be at least 10000"):
        await world.tools.read_offer("לאומי", "5000", 60, "6", "972", [], None)

    assert await world.options.list(CHECK) == []
    assert await world.awaiting.list(CHECK) == []
    assert not [event for event in world.sink.events if event.type.startswith("offer.")]


async def test_the_word_for_a_lender_is_refused_as_its_name(world: World) -> None:
    await world.tools.set_loan("רכב", "45000")

    with pytest.raises(ToolError, match="not its name"):
        await world.tools.read_offer("גוף מלווה", "20000", 24, "6.45", "934", ["prime"], None)
    with pytest.raises(ToolError, match="not its name"):
        await world.tools.save_offer([PRIME_TRACK], "הגוף המלווה")
    with pytest.raises(ToolError, match="not its name"):
        await world.tools.ask_offer("גוף מלווה", [], None)

    assert await world.options.list(CHECK) == []
    assert await world.awaiting.list(CHECK) == []


async def test_read_offer_needs_a_loan(world: World) -> None:
    with pytest.raises(ToolError, match="set_loan"):
        await world.tools.read_offer("לאומי", "45000", 60, "6", "972", [], None)


async def test_confirming_a_reading_saves_it_as_the_offer(world: World) -> None:
    awaiting_id = await avis_awaiting(world)
    (offer,) = await world.awaiting.list(CHECK)
    (fixed,) = [held for held in offer.readings if held.kind == "fixed_unlinked"]
    world.engine.simulations = [PRIME_SIMULATION]
    world.sink.events.clear()

    await world.tools.confirm_reading(awaiting_id, "fixed_unlinked")

    (option,) = await world.options.list(CHECK)
    (track,) = option.loan["tracks"]  # type: ignore[attr-defined]
    assert (track["annual_rate"], track["cpi_linked"]) == ("10.58", False)
    assert (option.source, option.lender) == ("offer", "אוויס")
    assert await world.awaiting.list(CHECK) == []
    assert world.events_of(OFFER_SETTLED) == [
        {"awaiting_id": awaiting_id, "kind": "fixed_unlinked", "reading": fixed.to_json()}
    ]


async def test_confirming_an_unknown_offer_or_kind_is_refused(world: World) -> None:
    awaiting_id = await avis_awaiting(world)

    with pytest.raises(AwaitingOfferNotFoundError):
        await world.tools.confirm_reading("nope", "fixed_unlinked")
    with pytest.raises(ToolError, match="prime_total"):
        await world.tools.confirm_reading(awaiting_id, "prime_total")

    assert len(await world.awaiting.list(CHECK)) == 1
    assert await world.options.list(CHECK) == []
