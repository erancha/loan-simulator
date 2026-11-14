"""The Postgres repositories keep each person's rows apart and restore values exactly."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from loan_agent.adapters.postgres.repositories import (
    PostgresCheckEventStore,
    PostgresCheckRepository,
    PostgresOptionRepository,
    PostgresProfileRepository,
    PostgresRecommendationRepository,
)
from loan_agent.domain.errors import CheckNotFoundError
from loan_agent.domain.models import Check, Goal, Option, OptionFigures, Profile, Recommendation
from loan_agent.platform.db import build_engine, session_factory

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
PERSON = "1001"
OTHER = "1002"


class Clock:
    def __init__(self) -> None:
        self.value = T0

    def __call__(self) -> datetime:
        return self.value


@dataclass
class Repos:
    clock: Clock
    profiles: PostgresProfileRepository
    checks: PostgresCheckRepository
    options: PostgresOptionRepository
    recommendations: PostgresRecommendationRepository
    events: PostgresCheckEventStore


@pytest.fixture
async def sessions(pg_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine(pg_url)
    yield session_factory(engine)
    await engine.dispose()


@pytest.fixture
def repos(sessions: async_sessionmaker[AsyncSession]) -> Repos:
    clock = Clock()
    return Repos(
        clock,
        PostgresProfileRepository(sessions, clock),
        PostgresCheckRepository(sessions),
        PostgresOptionRepository(sessions),
        PostgresRecommendationRepository(sessions),
        PostgresCheckEventStore(sessions),
    )


def make_check(check_id: str, user_id: str = PERSON, created_at: datetime = T0) -> Check:
    return Check(check_id, user_id, created_at, None, None)


def make_figures() -> OptionFigures:
    return OptionFigures(
        first_payment=Decimal("1550.00"),
        peak_payment=Decimal("1720.35"),
        worst_peak_payment=Decimal("1990.10"),
        worst_start=date(2029, 3, 1),
        worst_end=date(2031, 3, 1),
        balloon_due=None,
        total_paid=Decimal("101234.56"),
        rate_as_of=date(2026, 9, 1),
        cpi_as_of=date(2026, 8, 1),
    )


async def test_profile_round_trip_keeps_decimals(repos: Repos) -> None:
    assert await repos.profiles.get("fresh") == (Profile(), None)
    profile = Profile(
        net_fixed_income=Decimal("12500.50"),
        variable_income=Decimal(0),
        variable_income_minimum=None,
        fixed_expenses=Decimal("4200.00"),
        existing_loan_payments=None,
        savings=Decimal("80000.10"),
    )
    saved_at = await repos.profiles.save(PERSON, profile)
    restored, updated_at = await repos.profiles.get(PERSON)
    assert restored == profile
    assert isinstance(restored.net_fixed_income, Decimal)
    assert str(restored.net_fixed_income) == "12500.50"
    assert updated_at == saved_at == T0


async def test_check_of_another_person_is_not_found(repos: Repos) -> None:
    await repos.checks.add(make_check("c-own"))
    assert (await repos.checks.get(PERSON, "c-own")).id == "c-own"
    with pytest.raises(CheckNotFoundError):
        await repos.checks.get(OTHER, "c-own")
    with pytest.raises(CheckNotFoundError):
        await repos.checks.get(PERSON, "c-unknown")


async def test_checks_list_newest_first(repos: Repos) -> None:
    older, newer = "list-older", "list-newer"
    await repos.checks.add(make_check(newer, "lister", T0 + timedelta(hours=1)))
    await repos.checks.add(make_check(older, "lister", T0))
    await repos.checks.add(make_check("list-foreign", "someone-else", T0))
    assert [c.id for c in await repos.checks.list("lister")] == [newer, older]


async def test_check_goal_and_snapshot_round_trip(repos: Repos) -> None:
    await repos.checks.add(make_check("c-goal"))
    goal = Goal("car", Decimal("150000.00"))
    await repos.checks.set_goal("c-goal", goal)
    snapshot_at = T0 + timedelta(minutes=5)
    await repos.checks.snapshot_profile("c-goal", snapshot_at)
    check = await repos.checks.get(PERSON, "c-goal")
    assert check.goal == goal
    assert check.profile_snapshot_at == snapshot_at
    with pytest.raises(CheckNotFoundError):
        await repos.checks.set_goal("c-missing", goal)
    with pytest.raises(CheckNotFoundError):
        await repos.checks.snapshot_profile("c-missing", snapshot_at)


async def test_option_round_trip(repos: Repos) -> None:
    await repos.checks.add(make_check("c-opt"))
    loan = {"principal": "100000.00", "tracks": [{"rate": "4.5", "months": 60}]}
    option = Option("o-1", "c-opt", loan, "offer", "Bank X", date(2026, 10, 2), make_figures(), T0)
    await repos.options.add(option)
    assert await repos.options.get("c-opt", "o-1") == option
    assert await repos.options.list("c-opt") == [option]
    with pytest.raises(KeyError):
        await repos.options.get("c-opt", "o-missing")
    with pytest.raises(KeyError):
        await repos.options.get("c-other", "o-1")


async def test_recommendation_replaced_per_check(repos: Repos) -> None:
    await repos.checks.add(make_check("c-rec"))
    assert await repos.recommendations.latest("c-rec") is None

    def rec(preferred: str, reasoning: str) -> Recommendation:
        return Recommendation(
            "c-rec",
            preferred,
            None,
            reasoning,
            Decimal("90000.00"),
            Decimal("2000.00"),
            Decimal("5000.00"),
            Decimal("7000.55"),
            T0,
        )

    await repos.recommendations.save(rec("o-1", "first"))
    second = rec("o-2", "second")
    await repos.recommendations.save(second)
    assert await repos.recommendations.latest("c-rec") == second


async def test_event_seq_is_per_check_and_gapless(repos: Repos) -> None:
    await repos.checks.add(make_check("c-ev-a"))
    await repos.checks.add(make_check("c-ev-b"))
    assert await repos.events.append("c-ev-a", "message.user", {"text": "a"}) == 1
    assert await repos.events.append("c-ev-b", "message.user", {"text": "b"}) == 1
    assert await repos.events.append("c-ev-a", "message.assistant", {"text": "c"}) == 2
    events = await repos.events.list("c-ev-a", 0)
    assert [(e.seq, e.type, dict(e.data)) for e in events] == [
        (1, "message.user", {"text": "a"}),
        (2, "message.assistant", {"text": "c"}),
    ]
    assert [e.seq for e in await repos.events.list("c-ev-a", 1)] == [2]
    with pytest.raises(CheckNotFoundError):
        await repos.events.append("c-ev-missing", "message.user", {})


async def test_count_since_counts_one_persons_messages_across_checks(repos: Repos) -> None:
    for check_id, user in (
        ("c-cnt-1", "counter"),
        ("c-cnt-2", "counter"),
        ("c-cnt-x", "bystander"),
    ):
        await repos.checks.add(make_check(check_id, user))
    before = datetime.now(UTC)
    await repos.events.append("c-cnt-1", "message.user", {})
    await repos.events.append("c-cnt-1", "message.assistant", {})
    await repos.events.append("c-cnt-2", "message.user", {})
    await repos.events.append("c-cnt-x", "message.user", {})
    count, times = await repos.events.count_since("counter", "message.user", before)
    assert count == 2
    assert times == sorted(times)
    assert all(t > before for t in times)
    assert await repos.events.count_since("counter", "message.user", times[0]) == (1, times[1:])
    future = datetime.now(UTC) + timedelta(hours=1)
    assert await repos.events.count_since("counter", "message.user", future) == (0, [])


async def test_a_save_that_changes_nothing_keeps_the_save_time(repos: Repos) -> None:
    first = await repos.profiles.save("unchanged", Profile(savings=Decimal(35000)))
    repos.clock.value = T0 + timedelta(hours=1)

    assert await repos.profiles.save("unchanged", Profile(savings=Decimal("35000.00"))) == first
    assert (await repos.profiles.get("unchanged"))[1] == first

    later = await repos.profiles.save("unchanged", Profile(savings=Decimal(36000)))
    assert later == T0 + timedelta(hours=1)


async def test_delete_removes_the_check_and_everything_it_produced(repos: Repos) -> None:
    await repos.checks.add(make_check("c-del"))
    option = Option("o-del", "c-del", {}, "offer", "Bank X", date(2026, 10, 2), make_figures(), T0)
    await repos.options.add(option)
    await repos.recommendations.save(
        Recommendation(
            "c-del",
            "o-del",
            None,
            "why",
            Decimal("90000.00"),
            Decimal("2000.00"),
            Decimal("5000.00"),
            Decimal("7000.55"),
            T0,
        )
    )
    await repos.events.append("c-del", "message.user", {"text": "a"})

    await repos.checks.delete("c-del", "message.user", T0)

    with pytest.raises(CheckNotFoundError):
        await repos.checks.get(PERSON, "c-del")
    assert await repos.options.list("c-del") == []
    assert await repos.recommendations.latest("c-del") is None
    assert await repos.events.list("c-del", 0) == []


async def test_delete_keeps_the_recent_times_of_one_event_type_until_they_expire(
    repos: Repos,
) -> None:
    for check_id in ("c-kept", "c-live", "c-later"):
        await repos.checks.add(make_check(check_id, "keeper"))
    before = datetime.now(UTC)
    await repos.events.append("c-kept", "message.user", {})
    await repos.events.append("c-kept", "message.assistant", {})
    await repos.events.append("c-live", "message.user", {})

    await repos.checks.delete("c-kept", "message.user", before)

    count, times = await repos.events.count_since("keeper", "message.user", before)
    assert count == 2
    assert times == sorted(times)
    assert await repos.events.count_since("keeper", "message.assistant", before) == (0, [])

    await repos.checks.delete("c-later", "message.user", datetime.now(UTC) + timedelta(hours=1))

    assert (await repos.events.count_since("keeper", "message.user", before))[0] == 1


async def test_checks_whose_latest_matches_the_latest_event_of_that_type(repos: Repos) -> None:
    running = {"status": "running"}
    for check_id in ("c-end-running", "c-end-idle", "c-end-other", "c-end-empty"):
        await repos.checks.add(make_check(check_id, user_id=check_id))
    await repos.events.append("c-end-running", "message.user", {"text": "a"})
    await repos.events.append("c-end-running", "turn.status", running)
    await repos.events.append("c-end-idle", "turn.status", running)
    await repos.events.append("c-end-idle", "turn.status", {"status": "idle"})
    await repos.events.append("c-end-other", "turn.status", running)
    await repos.events.append("c-end-other", "message.assistant", running)

    ending = await repos.events.checks_whose_latest("turn.status", running)

    assert [check_id for check_id in ending if check_id.startswith("c-end-")] == [
        "c-end-other",
        "c-end-running",
    ]


async def test_profile_saved_after_snapshot_marks_check_stale(repos: Repos) -> None:
    await repos.checks.add(make_check("c-stale", "stale-person"))
    await repos.profiles.save("stale-person", Profile(savings=Decimal(1)))
    _, updated_at = await repos.profiles.get("stale-person")
    assert updated_at is not None
    await repos.checks.snapshot_profile("c-stale", updated_at)

    check = await repos.checks.get("stale-person", "c-stale")
    assert not check.is_stale(updated_at)
    repos.clock.value = T0 + timedelta(minutes=1)
    await repos.profiles.save("stale-person", Profile(savings=Decimal(2)))
    _, later = await repos.profiles.get("stale-person")
    assert check.is_stale(later)


async def test_archive_stamps_the_check_and_restore_clears_it(repos: Repos) -> None:
    await repos.checks.add(make_check("c-arch"))

    await repos.checks.archive("c-arch", T0 + timedelta(hours=1))

    assert (await repos.checks.get(PERSON, "c-arch")).archived_at == T0 + timedelta(hours=1)
    with pytest.raises(CheckNotFoundError):
        await repos.checks.archive("c-missing", T0)

    await repos.checks.restore("c-arch")

    assert (await repos.checks.get(PERSON, "c-arch")).archived_at is None


async def test_clone_copies_options_recommendation_and_events_but_the_left_out_types(
    repos: Repos,
) -> None:
    await repos.checks.add(make_check("c-src", "cloner"))
    await repos.checks.set_goal("c-src", Goal("car", Decimal("150000.00")))
    option = Option("o-1", "c-src", {}, "offer", "Bank X", date(2026, 10, 2), make_figures(), T0)
    await repos.options.add(option)
    recommendation = Recommendation(
        "c-src",
        "o-1",
        None,
        "why",
        Decimal("90000.00"),
        Decimal("2000.00"),
        Decimal("5000.00"),
        Decimal("7000.55"),
        T0,
    )
    await repos.recommendations.save(recommendation)
    before = datetime.now(UTC)
    await repos.events.append("c-src", "message.user", {"text": "a"})
    await repos.events.append("c-src", "check.archived", {})
    await repos.events.append("c-src", "message.assistant", {"text": "b"})
    source = await repos.checks.get("cloner", "c-src")
    clone = Check("c-copy", "cloner", T0 + timedelta(hours=1), source.goal, T0)

    await repos.checks.clone("c-src", clone, ("check.archived",))

    assert await repos.checks.get("cloner", "c-copy") == clone
    assert await repos.options.list("c-copy") == [replace(option, check_id="c-copy")]
    assert await repos.recommendations.latest("c-copy") == replace(
        recommendation, check_id="c-copy"
    )
    copied = await repos.events.list("c-copy", 0)
    assert [(e.seq, e.type, dict(e.data)) for e in copied] == [
        (1, "message.user", {"text": "a"}),
        (2, "message.assistant", {"text": "b"}),
    ]
    assert (await repos.events.count_since("cloner", "message.user", before))[0] == 1
