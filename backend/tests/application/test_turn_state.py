"""The turn state tells the model, at every call, the check's loan, term, ceiling, finances,
saved offers, awaiting offers and recommendation, and the finances an earlier check of the person
holds."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from fakes import (
    NOW,
    PRIME_SIMULATION,
    PRIME_TRACK,
    Clock,
    FakeLoanEngine,
    Ids,
    InMemoryAwaitingOfferRepository,
    InMemoryCheckRepository,
    InMemoryOptionRepository,
    InMemoryRecommendationRepository,
    RecordingSink,
    awaiting_offer,
    engine_fixture,
)
from loan_agent.adapters.engine_mcp import offer_readings_of
from loan_agent.application.check_tools import ToolDeps
from loan_agent.application.turn_state import turn_state
from loan_agent.domain.models import (
    AwaitingOffer,
    Check,
    Finances,
    LoanRequest,
    Option,
    OptionFigures,
    Recommendation,
)
from loan_agent.ports.events import OPTION_SAVED, SCENARIO_SHOWN

PERSON = "1001"
SCENARIO_DEFAULTS = {
    "cpi_per_year": "2.0",
    "prime_per_year": "0",
    "cpi_like_last_years": None,
    "prime_like_last_years": None,
}
CHECK = "check-1"
EARLIER_CHECK = "check-0"


@pytest.fixture
async def deps() -> ToolDeps:
    checks = InMemoryCheckRepository()
    await checks.add(Check(CHECK, PERSON, NOW, None, None, None, None, Finances()))
    return ToolDeps(
        checks=checks,
        options=InMemoryOptionRepository(),
        awaiting=InMemoryAwaitingOfferRepository(),
        recommendations=InMemoryRecommendationRepository(),
        engine=FakeLoanEngine(),
        sink=RecordingSink(),
        clock=Clock(),
        new_id=Ids("option"),
    )


async def add_two_offers(deps: ToolDeps) -> None:
    """Two real offers, so a recommendation compares them."""
    for option_id, lender in (("option-1", "לאומי"), ("option-2", "מקס")):
        await deps.options.add(
            Option(
                option_id,
                CHECK,
                {"tracks": [PRIME_TRACK]},
                "offer",
                lender,
                None,
                None,
                PRIME_SIMULATION.figures,
                NOW,
            )
        )


async def test_turn_state_of_a_new_check_has_nothing_yet(deps: ToolDeps) -> None:
    block = await turn_state(PERSON, CHECK, deps)

    assert block.splitlines() == [
        "loan: none yet",
        "term_months: none",
        "payment_ceiling: none",
        "ceiling_source: none",
        "ceiling_basis: none",
        "net_fixed_income: not told",
        "fixed_expenses: not told",
        "missing: net_fixed_income, fixed_expenses",
        "previous_finances: none",
        "option_counts: real offers 0, examples 0",
        "offers: none",
        "awaiting_offers: none",
        "recommendation: none",
        "scenarios_shown: none",
        "certainty_price: none",
    ]


async def test_turn_state_lists_the_saved_offers_and_the_awaiting_ones(deps: ToolDeps) -> None:
    track = {**PRIME_TRACK, "principal": "45000", "term_months": 60, "prime_spread": "6"}
    await deps.options.add(
        Option(
            "option-1",
            CHECK,
            {"tracks": [track]},
            "offer",
            "לאומי",
            None,
            None,
            PRIME_SIMULATION.figures,
            NOW,
        )
    )
    avis = offer_readings_of(engine_fixture("offer_readings"))
    await deps.awaiting.save(
        AwaitingOffer(
            id="option-2",
            check_id=CHECK,
            lender="אוויס",
            amount=Decimal(45000),
            term_months=60,
            stated_rate=None,
            monthly_payment=Decimal(969),
            payment_rate=avis.payment_rate,
            type_words=("fixed",),
            readings=avis.readings,
            likely="fixed_unlinked",
            prime=avis.prime,
            rate_as_of=avis.rate_as_of,
            created_at=NOW,
        )
    )

    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()

    assert (
        "offers: option-1: source offer, lender לאומי, rate prime + 6, not linked, "
        "term_months 60, first_payment 1888, worst_past_payment 2039 (2022-04 to 2026-03), "
        "total_paid 90623, total_paid_in_past_periods 90550-96665, price (interest_cost 45623 on "
        "45000; rate_today 6.25%, below the average bank rate on consumer loans of 7.9% as of "
        "2026-08)"
    ) in lines
    assert "option_counts: real offers 1, examples 0" in lines
    assert (
        "awaiting_offers: option-2: lender אוויס, monthly_payment 969, readings "
        "fixed_unlinked/prime_margin/fixed_linked, likely fixed_unlinked"
    ) in lines


async def test_turn_state_says_an_awaiting_offer_quoted_for_less_awaits_the_amount(
    deps: ToolDeps,
) -> None:
    await deps.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(45000)))
    await deps.awaiting.save(
        awaiting_offer(CHECK, "awaiting-1", "מקס", Decimal(934), Decimal(20000))
    )

    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()

    assert (
        "awaiting_offers: awaiting-1: lender מקס, monthly_payment 934, readings fixed_unlinked, "
        "likely none, quoted for 20000, less than the loan: awaits the lender's answer on "
        "lending the loan amount on the same terms"
    ) in lines


async def test_turn_state_reports_an_unchecked_recommendation_and_no_ceiling(
    deps: ToolDeps,
) -> None:
    await deps.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(60000)))
    await deps.checks.set_term(CHECK, 60)
    await deps.recommendations.save(
        Recommendation(CHECK, "option-1", None, "הזולה ביותר", Decimal(60000), None, NOW)
    )
    await add_two_offers(deps)

    lines = set((await turn_state(PERSON, CHECK, deps)).splitlines())

    assert {
        "loan: purpose: רכב, amount: 60000",
        "term_months: 60",
        "payment_ceiling: none",
        "ceiling_source: none",
        "recommendation: unchecked",
    } <= lines


async def test_turn_state_reports_a_checked_recommendation_with_its_ceiling(
    deps: ToolDeps,
) -> None:
    await deps.checks.set_loan(CHECK, LoanRequest(None, Decimal(100000)))
    await deps.checks.set_finances(
        CHECK, Finances(net_fixed_income=Decimal(12000), fixed_expenses=Decimal(6000))
    )
    await deps.checks.set_ceiling(CHECK, Decimal(3000), "finances")
    await deps.recommendations.save(
        Recommendation(CHECK, "option-1", None, "בתוך התקרה", Decimal(100000), Decimal(3000), NOW)
    )
    await add_two_offers(deps)

    lines = set((await turn_state(PERSON, CHECK, deps)).splitlines())

    assert {
        "loan: purpose: none, amount: 100000",
        "payment_ceiling: 3000",
        "ceiling_source: finances",
        "recommendation: checked",
    } <= lines


async def test_turn_state_explains_a_ceiling_derived_from_the_finances(deps: ToolDeps) -> None:
    told = Finances(net_fixed_income=Decimal(20000), fixed_expenses=Decimal(10600))
    await deps.checks.set_finances(CHECK, told)
    await deps.checks.set_ceiling(CHECK, Decimal("4700.00"), "finances")

    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()

    assert (
        "ceiling_basis: the lower of 30% of net_fixed_income = 6000.00 and 50% of "
        "(net_fixed_income minus fixed_expenses) = 4700.00"
    ) in lines


async def test_turn_state_gives_no_basis_for_a_stated_ceiling(deps: ToolDeps) -> None:
    await deps.checks.set_ceiling(CHECK, Decimal(1500), "stated")

    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()

    assert "ceiling_basis: none" in lines


async def test_turn_state_offers_the_previous_checks_finances(deps: ToolDeps) -> None:
    told = Finances(net_fixed_income=Decimal(12000), fixed_expenses=Decimal(6000))
    earlier = Check(EARLIER_CHECK, PERSON, NOW - timedelta(days=1), None, None, None, None, told)
    await deps.checks.add(earlier)
    await deps.checks.add(replace(earlier, id="check-other", user_id="2002"))

    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()

    assert "previous_finances: net_fixed_income: 12000, fixed_expenses: 6000" in lines
    assert "missing: net_fixed_income, fixed_expenses" in lines


async def test_turn_state_says_a_recommendation_of_one_option_alone_evaluates_it(
    deps: ToolDeps,
) -> None:
    await deps.checks.set_loan(CHECK, LoanRequest(None, Decimal(80000)))
    await deps.checks.set_term(CHECK, 48)
    offer = Option(
        "option-1",
        CHECK,
        {"tracks": [PRIME_TRACK]},
        "offer",
        "לאומי",
        None,
        None,
        PRIME_SIMULATION.figures,
        NOW,
    )
    await deps.options.add(offer)
    await deps.recommendations.save(
        Recommendation(CHECK, "option-1", None, "ההצעה היחידה", Decimal(80000), None, NOW)
    )

    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()
    assert (
        "recommendation: unchecked, of one option alone: evaluate it, never recommend it" in lines
    )

    await deps.options.add(replace(offer, id="option-2", lender="מקס"))
    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()
    assert "recommendation: unchecked" in lines


def scenario_row(option_id: str, lender: str | None, total: str) -> dict[str, object]:
    return {"option_id": option_id, "lender": lender, "scenario": {"total_paid": total}}


async def test_turn_state_names_each_scenario_shown_since_the_latest_option_with_its_cheapest(
    deps: ToolDeps,
) -> None:
    await deps.sink.emit(
        CHECK,
        SCENARIO_SHOWN,
        {
            "scenario": SCENARIO_DEFAULTS | {"cpi_per_year": "7"},
            "named": ["cpi_per_year"],
            "rows": [scenario_row("option-0", "ישן", "1")],
        },
    )
    await deps.sink.emit(CHECK, OPTION_SAVED, {})
    await deps.sink.emit(
        CHECK,
        SCENARIO_SHOWN,
        {
            "scenario": SCENARIO_DEFAULTS | {"cpi_per_year": "5"},
            "named": ["cpi_per_year"],
            "rows": [
                scenario_row("option-1", "פריסבי", "113915.90"),
                scenario_row("option-2", "הפועלים", "122348.85"),
                scenario_row("option-3", None, "121658.37"),
            ],
        },
    )
    await deps.sink.emit(
        CHECK,
        SCENARIO_SHOWN,
        {
            "scenario": SCENARIO_DEFAULTS | {"cpi_per_year": "2.38", "cpi_like_last_years": 3},
            "named": ["cpi_like_last_years"],
            "rows": [
                scenario_row("option-1", "פריסבי", "113915.90"),
                scenario_row("option-2", "הפועלים", "114519.99"),
            ],
        },
    )

    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()

    assert (
        "scenarios_shown: cpi_per_year 5, prime_per_year 0 (default): cheapest option-1 "
        "(פריסבי), ahead of option-3 (example) by a ברור gap; cpi_per_year 2.38 (as over the "
        "last 3 years), prime_per_year 0 (default): cheapest option-1 (פריסבי), ahead of "
        "option-2 (הפועלים) by a במקצת gap"
    ) in lines


async def test_turn_state_says_when_every_past_period_costs_more_than_the_expected_total(
    deps: ToolDeps,
) -> None:
    figures = replace(PRIME_SIMULATION.figures, total_paid=Decimal(90000))
    await deps.options.add(
        Option(
            "option-1", CHECK, {"tracks": [PRIME_TRACK]}, "offer", "לאומי", None, None, figures, NOW
        )
    )

    (offers,) = [
        line
        for line in (await turn_state(PERSON, CHECK, deps)).splitlines()
        if line.startswith("offers:")
    ]

    assert "total_paid_in_past_periods 90550-96665, every one above total_paid" in offers


def steady(figures: OptionFigures, total: str) -> OptionFigures:
    """The figures of a payment that never moves, with the given total."""
    return replace(
        figures,
        total_paid=Decimal(total),
        worst_peak_payment=None,
        worst_start=None,
        worst_end=None,
        total_paid_low=None,
        total_paid_high=None,
    )


async def test_turn_state_prices_a_steady_payment_against_each_moving_option_of_its_term(
    deps: ToolDeps,
) -> None:
    moving = PRIME_SIMULATION.figures
    for option_id, lender, track, figures in (
        ("option-1", "הפועלים", PRIME_TRACK, moving),
        ("option-2", "לאומי", PRIME_TRACK, steady(moving, "95000.40")),
        ("option-3", "מקס", PRIME_TRACK, steady(moving, "96665.48")),
        ("option-4", "כאל", {**PRIME_TRACK, "term_months": 36}, steady(moving, "99000")),
    ):
        await deps.options.add(
            Option(option_id, CHECK, {"tracks": [track]}, "offer", lender, None, None, figures, NOW)
        )

    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()

    assert (
        "certainty_price: option-2 (לאומי) total_paid is 4377 above the total_paid of option-1 "
        "(הפועלים) and 1665 below its highest total in past periods; option-3 (מקס) total_paid "
        "is 6042 above the total_paid of option-1 (הפועלים) and equal to its highest total in "
        "past periods"
    ) in lines
