"""A profile save that changes a figure archives every check recommended from the replaced
figures, with an event that holds the whole replaced profile and what changed; a check still
collecting, a check already stale and a save of the same figures archive nothing."""

from datetime import datetime, timedelta
from decimal import Decimal

from fakes import (
    NOW,
    Clock,
    InMemoryCheckEventStore,
    InMemoryCheckRepository,
    InMemoryProfileRepository,
    RecordingSink,
)
from loan_agent.application.profile_saving import save_profile
from loan_agent.domain.models import Check, Goal, Profile
from loan_agent.ports.events import CHECK_ARCHIVED

PERSON = "1001"
GOAL = Goal("רכב", Decimal(55000))
PROFILE = Profile(
    savings=Decimal(35000),
    net_fixed_income=Decimal(8000),
    variable_income=Decimal(5000),
    variable_income_minimum=Decimal(2000),
    fixed_expenses=Decimal(6000),
    existing_loan_payments=Decimal(0),
)
LATER = NOW + timedelta(minutes=5)


class Setup:
    def __init__(self) -> None:
        self.clock = Clock()
        self.profiles = InMemoryProfileRepository(self.clock)
        self.checks = InMemoryCheckRepository()
        InMemoryCheckEventStore(self.checks, self.clock)
        self.sink = RecordingSink()
        self.profiles.rows[PERSON] = (PROFILE, NOW)

    def check(self, check_id: str, snapshot_at: datetime | None) -> None:
        self.checks.rows[check_id] = Check(check_id, PERSON, NOW, GOAL, snapshot_at)

    async def save(self, **update: object) -> list[str]:
        self.clock.value = LATER
        saved = await save_profile(
            PERSON, update, self.profiles, self.checks, self.sink, self.clock
        )
        return saved.archived


async def test_a_changed_figure_archives_the_checks_recommended_from_the_replaced_profile() -> None:
    setup = Setup()
    setup.check("recommended", NOW)

    assert await setup.save(savings="23000") == ["recommended"]

    assert setup.checks.rows["recommended"].archived_at == LATER
    (event,) = setup.sink.events
    assert (event.check_id, event.type) == ("recommended", CHECK_ARCHIVED)
    assert event.data == {
        "previous_profile": {
            "savings": "35000",
            "net_fixed_income": "8000",
            "variable_income": "5000",
            "variable_income_minimum": "2000",
            "fixed_expenses": "6000",
            "existing_loan_payments": "0",
        },
        "changes": [{"field": "savings", "from": "35000", "to": "23000"}],
        "archived_at": LATER.isoformat(),
    }


async def test_checks_without_a_recommendation_or_already_stale_stay_open() -> None:
    setup = Setup()
    setup.check("collecting", None)
    setup.check("stale", NOW - timedelta(1))

    assert await setup.save(fixed_expenses="6500") == []

    assert setup.checks.rows["collecting"].archived_at is None
    assert setup.checks.rows["stale"].archived_at is None
    assert setup.sink.events == []


async def test_a_save_of_the_same_figures_archives_nothing() -> None:
    setup = Setup()
    setup.check("recommended", NOW)

    assert await setup.save(savings="35000.00") == []

    assert setup.checks.rows["recommended"].archived_at is None
