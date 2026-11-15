"""The turn state tells the model, at every call, the check's loan, term, ceiling, finances and
recommendation, and the finances an earlier check of the person holds."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from fakes import (
    NOW,
    Clock,
    FakeLoanEngine,
    Ids,
    InMemoryCheckRepository,
    InMemoryOptionRepository,
    InMemoryRecommendationRepository,
    RecordingSink,
)
from loan_agent.application.check_tools import ToolDeps
from loan_agent.application.turn_state import turn_state
from loan_agent.domain.models import Check, Finances, LoanRequest, Recommendation

PERSON = "1001"
CHECK = "check-1"
EARLIER_CHECK = "check-0"


@pytest.fixture
async def deps() -> ToolDeps:
    checks = InMemoryCheckRepository()
    await checks.add(Check(CHECK, PERSON, NOW, None, None, None, None, Finances()))
    return ToolDeps(
        checks=checks,
        options=InMemoryOptionRepository(),
        recommendations=InMemoryRecommendationRepository(),
        engine=FakeLoanEngine(),
        sink=RecordingSink(),
        clock=Clock(),
        new_id=Ids("option"),
    )


async def test_turn_state_of_a_new_check_has_nothing_yet(deps: ToolDeps) -> None:
    block = await turn_state(PERSON, CHECK, deps)

    assert block.splitlines() == [
        "loan: none yet",
        "term_months: none",
        "payment_ceiling: none",
        "ceiling_source: none",
        "net_fixed_income: not told",
        "fixed_expenses: not told",
        "missing: net_fixed_income, fixed_expenses",
        "previous_finances: none",
        "recommendation: none",
    ]


async def test_turn_state_reports_an_unchecked_recommendation_and_no_ceiling(
    deps: ToolDeps,
) -> None:
    await deps.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(60000)))
    await deps.checks.set_term(CHECK, 60)
    await deps.recommendations.save(
        Recommendation(CHECK, "option-1", None, "הזולה ביותר", Decimal(60000), None, NOW)
    )

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
    await deps.checks.set_ceiling(CHECK, Decimal(3000), "finances")
    await deps.recommendations.save(
        Recommendation(CHECK, "option-1", None, "בתוך התקרה", Decimal(100000), Decimal(3000), NOW)
    )

    lines = set((await turn_state(PERSON, CHECK, deps)).splitlines())

    assert {
        "loan: purpose: none, amount: 100000",
        "payment_ceiling: 3000",
        "ceiling_source: finances",
        "recommendation: checked",
    } <= lines


async def test_turn_state_offers_the_previous_checks_finances(deps: ToolDeps) -> None:
    told = Finances(net_fixed_income=Decimal(12000), fixed_expenses=Decimal(6000))
    earlier = Check(EARLIER_CHECK, PERSON, NOW - timedelta(days=1), None, None, None, None, told)
    await deps.checks.add(earlier)
    await deps.checks.add(replace(earlier, id="check-other", user_id="2002"))

    lines = (await turn_state(PERSON, CHECK, deps)).splitlines()

    assert "previous_finances: net_fixed_income: 12000, fixed_expenses: 6000" in lines
    assert "missing: net_fixed_income, fixed_expenses" in lines
