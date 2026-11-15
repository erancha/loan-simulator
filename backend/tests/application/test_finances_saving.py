"""Saving a check's finances merges the figures told so far, and once both are known derives the
payment ceiling from the engine and stores it with source "finances"."""

from dataclasses import replace
from decimal import Decimal

import pytest

from fakes import (
    ASSESSED_BOUNDS,
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
from loan_agent.application.finances_saving import save_finances
from loan_agent.domain.errors import FinancesError
from loan_agent.domain.models import Check, Finances
from loan_agent.ports.engine import EngineError
from loan_agent.ports.events import FINANCES_UPDATED

PERSON = "1001"
CHECK = "check-1"


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


def engine(deps: ToolDeps) -> FakeLoanEngine:
    assert isinstance(deps.engine, FakeLoanEngine)
    return deps.engine


def sink(deps: ToolDeps) -> RecordingSink:
    assert isinstance(deps.sink, RecordingSink)
    return deps.sink


async def test_save_finances_derives_the_ceiling_once_both_are_known(deps: ToolDeps) -> None:
    partial = await save_finances(CHECK, PERSON, {"net_fixed_income": "18000"}, deps)

    assert partial.finances == Finances(net_fixed_income=Decimal(18000))
    assert partial.payment_ceiling is None
    assert engine(deps).calls == []
    assert sink(deps).events[-1].data == {
        "finances": {"net_fixed_income": "18000", "fixed_expenses": None},
        "missing": ["fixed_expenses"],
        "payment_ceiling": None,
        "ceiling_source": None,
    }

    complete = await save_finances(CHECK, PERSON, {"fixed_expenses": 9000}, deps)

    assert engine(deps).calls == [
        ("assess", {"net_fixed_income": "18000", "fixed_expenses": "9000"})
    ]
    assert (complete.payment_ceiling, complete.ceiling_source) == (Decimal("4700.00"), "finances")
    assert complete == await deps.checks.get(PERSON, CHECK)
    event = sink(deps).events[-1]
    assert (event.check_id, event.type) == (CHECK, FINANCES_UPDATED)
    assert event.data == {
        "finances": {"net_fixed_income": "18000", "fixed_expenses": "9000"},
        "missing": [],
        "payment_ceiling": "4700.00",
        "ceiling_source": "finances",
    }


async def test_finances_replace_a_stated_ceiling(deps: ToolDeps) -> None:
    await deps.checks.set_ceiling(CHECK, Decimal(2000), "stated")
    engine(deps).bounds = replace(ASSESSED_BOUNDS, payment_ceiling=Decimal("3000.00"))

    saved = await save_finances(
        CHECK, PERSON, {"net_fixed_income": "12000", "fixed_expenses": "6000"}, deps
    )

    assert (saved.payment_ceiling, saved.ceiling_source) == (Decimal("3000.00"), "finances")


async def test_a_bad_figure_is_refused_before_anything_is_saved(deps: ToolDeps) -> None:
    with pytest.raises(FinancesError, match="fixed_expenses cannot be negative"):
        await save_finances(CHECK, PERSON, {"fixed_expenses": "-100"}, deps)

    assert (await deps.checks.get(PERSON, CHECK)).finances == Finances()
    assert sink(deps).events == []


async def test_a_partial_save_reports_the_stated_ceiling_the_check_keeps(deps: ToolDeps) -> None:
    await deps.checks.set_ceiling(CHECK, Decimal(2000), "stated")

    saved = await save_finances(CHECK, PERSON, {"net_fixed_income": "12000"}, deps)

    assert (saved.payment_ceiling, saved.ceiling_source) == (Decimal(2000), "stated")
    data = sink(deps).events[-1].data
    assert (data["payment_ceiling"], data["ceiling_source"]) == ("2000", "stated")


async def test_an_engine_refusal_leaves_the_figures_and_the_ceiling_unchanged(
    deps: ToolDeps,
) -> None:
    await save_finances(
        CHECK, PERSON, {"net_fixed_income": "18000", "fixed_expenses": "9000"}, deps
    )
    before = await deps.checks.get(PERSON, CHECK)
    sink(deps).events.clear()
    engine(deps).assess_error = EngineError("profile.net_fixed_income: too large")

    with pytest.raises(EngineError, match="too large"):
        await save_finances(CHECK, PERSON, {"net_fixed_income": "99000"}, deps)

    assert await deps.checks.get(PERSON, CHECK) == before
    assert sink(deps).events == []
