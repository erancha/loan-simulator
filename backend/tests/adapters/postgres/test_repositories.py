"""The Postgres repositories keep each person's rows apart and restore values exactly."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from loan_agent.adapters.postgres.orm import CheckRow
from loan_agent.adapters.postgres.repositories import (
    PostgresAwaitingOfferRepository,
    PostgresCheckEventStore,
    PostgresCheckRepository,
    PostgresOptionRepository,
    PostgresRecommendationRepository,
)
from loan_agent.domain.errors import AwaitingOfferNotFoundError, CheckNotFoundError
from loan_agent.domain.models import (
    AwaitingOffer,
    Check,
    Finances,
    LoanRequest,
    Option,
    OptionFigures,
    OptionPrice,
    Reading,
    Recommendation,
)
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
    checks: PostgresCheckRepository
    options: PostgresOptionRepository
    recommendations: PostgresRecommendationRepository
    events: PostgresCheckEventStore
    awaiting: PostgresAwaitingOfferRepository


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
        PostgresCheckRepository(sessions),
        PostgresOptionRepository(sessions),
        PostgresRecommendationRepository(sessions),
        PostgresCheckEventStore(sessions),
        PostgresAwaitingOfferRepository(sessions),
    )


def make_check(check_id: str, user_id: str = PERSON, created_at: datetime = T0) -> Check:
    return Check(check_id, user_id, created_at, None, None, None, None, Finances())


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
        price=OptionPrice(
            rate_today=Decimal("10.75"),
            against_market="above",
            market_rate=Decimal("7.9"),
            market_rate_month=date(2026, 8, 1),
        ),
    )


def make_awaiting(awaiting_id: str, check_id: str, created_at: datetime = T0) -> AwaitingOffer:
    track = {"principal": "45000", "term_months": 60, "rate_kind": "fixed", "cpi_linked": True}
    return AwaitingOffer(
        id=awaiting_id,
        check_id=check_id,
        lender="בנק הפועלים",
        amount=Decimal(45000),
        term_months=60,
        stated_rate=Decimal("5.83"),
        monthly_payment=Decimal("969.00"),
        payment_rate=Decimal("10.58"),
        type_words=("fixed", "linked"),
        readings=(Reading("fixed_linked", track, Decimal("970.61"), Decimal("10.58"), True),),
        likely="fixed_linked",
        prime=Decimal("4.75"),
        rate_as_of=date(2026, 10, 20),
        created_at=created_at,
    )


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


async def test_a_check_round_trips_its_loan_term_ceiling_and_finances(repos: Repos) -> None:
    await repos.checks.add(make_check("c-fields"))
    fresh = await repos.checks.get(PERSON, "c-fields")
    assert (fresh.loan, fresh.term_months, fresh.payment_ceiling, fresh.ceiling_source) == (
        None,
        None,
        None,
        None,
    )
    assert fresh.finances == Finances()

    await repos.checks.set_loan("c-fields", LoanRequest(None, Decimal("150000.00")))
    await repos.checks.set_term("c-fields", 48)
    await repos.checks.set_ceiling("c-fields", Decimal("2500.50"), "finances")
    await repos.checks.set_finances("c-fields", Finances(Decimal("12500.50"), None))

    check = await repos.checks.get(PERSON, "c-fields")
    assert check.loan == LoanRequest(None, Decimal("150000.00"))
    assert str(check.loan.amount if check.loan else None) == "150000.00"
    assert check.term_months == 48
    assert check.payment_ceiling == Decimal("2500.50")
    assert check.ceiling_source == "finances"
    assert check.finances == Finances(Decimal("12500.50"), None)
    for call in (
        repos.checks.set_loan("c-missing", LoanRequest("רכב", Decimal(1))),
        repos.checks.set_term("c-missing", 12),
        repos.checks.set_ceiling("c-missing", Decimal(1), "stated"),
        repos.checks.set_finances("c-missing", Finances()),
    ):
        with pytest.raises(CheckNotFoundError):
            await call


async def test_latest_finances_skips_the_current_check_and_incomplete_ones(repos: Repos) -> None:
    person = "reuser"
    complete_old = Finances(Decimal("10000.00"), Decimal("4000.00"))
    complete_new = Finances(Decimal("11000.00"), Decimal("4500.00"))
    for check_id, hours in (("c-fin-old", 0), ("c-fin-new", 1), ("c-fin-partial", 2)):
        await repos.checks.add(make_check(check_id, person, T0 + timedelta(hours=hours)))
    await repos.checks.add(make_check("c-fin-current", person, T0 + timedelta(hours=3)))
    await repos.checks.add(make_check("c-fin-foreign", "someone-else", T0 + timedelta(hours=4)))
    await repos.checks.set_finances("c-fin-old", complete_old)
    await repos.checks.set_finances("c-fin-new", complete_new)
    await repos.checks.set_finances("c-fin-partial", Finances(Decimal("1.00"), None))
    await repos.checks.set_finances("c-fin-current", Finances(Decimal("9.00"), Decimal("9.00")))
    await repos.checks.set_finances("c-fin-foreign", Finances(Decimal("8.00"), Decimal("8.00")))

    assert await repos.checks.latest_finances(person, "c-fin-current") == complete_new
    assert await repos.checks.latest_finances("nobody", "c-x") is None
    await repos.checks.delete("c-fin-new", "message.user", T0)
    assert await repos.checks.latest_finances(person, "c-fin-current") == complete_old


async def test_a_stored_finances_object_with_a_missing_figure_is_refused(
    repos: Repos, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await repos.checks.add(make_check("c-partial"))
    async with sessions.begin() as session:
        await session.execute(
            update(CheckRow)
            .where(CheckRow.id == "c-partial")
            .values(finances={"net_fixed_income": "1"})
        )

    with pytest.raises(KeyError):
        await repos.checks.get(PERSON, "c-partial")


async def test_option_round_trip(repos: Repos) -> None:
    await repos.checks.add(make_check("c-opt"))
    loan = {"principal": "100000.00", "tracks": [{"rate": "4.5", "months": 60}]}
    option = Option(
        "o-1", "c-opt", loan, "offer", "Bank X", date(2026, 10, 2), None, make_figures(), T0
    )
    await repos.options.add(option)
    assert await repos.options.get("c-opt", "o-1") == option
    assert await repos.options.list("c-opt") == [option]
    with pytest.raises(KeyError):
        await repos.options.get("c-opt", "o-missing")
    with pytest.raises(KeyError):
        await repos.options.get("c-other", "o-1")


async def test_option_remove_takes_only_the_named_options_of_the_check(repos: Repos) -> None:
    for check_id in ("c-rm", "c-keep"):
        await repos.checks.add(make_check(check_id))
    loan = {"tracks": [{"principal": "100000.00", "term_months": 60}]}

    def option(option_id: str, check_id: str) -> Option:
        return Option(option_id, check_id, loan, "example", None, None, None, make_figures(), T0)

    kept = [option("o-3", "c-rm"), option("o-1", "c-keep")]
    for each in [option("o-1", "c-rm"), option("o-2", "c-rm"), *kept]:
        await repos.options.add(each)

    await repos.options.remove("c-rm", ["o-1", "o-2"])

    assert await repos.options.list("c-rm") == kept[:1]
    assert await repos.options.list("c-keep") == kept[1:]


async def test_an_awaiting_offer_round_trips(repos: Repos) -> None:
    await repos.checks.add(make_check("c-await"))
    offer = make_awaiting("a-1", "c-await")
    bare = replace(
        make_awaiting("a-2", "c-await", T0 + timedelta(hours=1)),
        stated_rate=None,
        payment_rate=None,
        type_words=(),
        likely=None,
    )

    await repos.awaiting.save(offer)
    await repos.awaiting.save(bare)

    assert await repos.awaiting.get("c-await", "a-1") == offer
    assert await repos.awaiting.list("c-await") == [offer, bare]


async def test_saving_an_awaiting_offer_again_replaces_it_in_its_place(repos: Repos) -> None:
    await repos.checks.add(make_check("c-again"))
    first = make_awaiting("a-1", "c-again")
    await repos.awaiting.save(first)
    await repos.awaiting.save(make_awaiting("a-2", "c-again", T0 + timedelta(hours=1)))
    changed = replace(first, lender="מזרחי טפחות", monthly_payment=Decimal("1012.40"))

    await repos.awaiting.save(changed)

    assert [o.id for o in await repos.awaiting.list("c-again")] == ["a-1", "a-2"]
    assert await repos.awaiting.get("c-again", "a-1") == changed


async def test_an_awaiting_offer_saved_again_later_keeps_its_place(repos: Repos) -> None:
    await repos.checks.add(make_check("c-later-save"))
    first = make_awaiting("a-1", "c-later-save")
    await repos.awaiting.save(first)
    await repos.awaiting.save(make_awaiting("a-2", "c-later-save", T0 + timedelta(hours=1)))

    await repos.awaiting.save(replace(first, created_at=T0 + timedelta(hours=2)))

    assert [o.id for o in await repos.awaiting.list("c-later-save")] == ["a-1", "a-2"]


async def test_an_awaiting_offer_the_check_does_not_hold_is_not_found(repos: Repos) -> None:
    await repos.checks.add(make_check("c-held"))
    await repos.checks.add(make_check("c-other-held"))
    await repos.awaiting.save(make_awaiting("a-1", "c-other-held"))

    with pytest.raises(AwaitingOfferNotFoundError):
        await repos.awaiting.get("c-held", "a-1")
    with pytest.raises(AwaitingOfferNotFoundError):
        await repos.awaiting.get("c-held", "a-unknown")


async def test_remove_drops_only_that_awaiting_offer(repos: Repos) -> None:
    await repos.checks.add(make_check("c-remove"))
    await repos.awaiting.save(make_awaiting("a-1", "c-remove"))
    kept = make_awaiting("a-2", "c-remove", T0 + timedelta(hours=1))
    await repos.awaiting.save(kept)

    await repos.awaiting.remove("c-remove", "a-1")

    assert await repos.awaiting.list("c-remove") == [kept]


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
            T0,
        )

    await repos.recommendations.save(rec("o-1", "first"))
    second = rec("o-2", "second")
    await repos.recommendations.save(second)
    assert await repos.recommendations.latest("c-rec") == second

    await repos.recommendations.remove("c-rec")
    assert await repos.recommendations.latest("c-rec") is None
    await repos.recommendations.remove("c-rec")


async def test_event_seq_is_per_check_and_gapless(repos: Repos) -> None:
    await repos.checks.add(make_check("c-ev-a"))
    await repos.checks.add(make_check("c-ev-b"))
    assert (await repos.events.append("c-ev-a", "message.user", {"text": "a"})).seq == 1
    assert (await repos.events.append("c-ev-b", "message.user", {"text": "b"})).seq == 1
    appended = await repos.events.append("c-ev-a", "message.assistant", {"text": "c"})
    assert appended.seq == 2
    events = await repos.events.list("c-ev-a", 0)
    assert appended == events[-1]
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


async def test_delete_removes_the_check_and_everything_it_produced(repos: Repos) -> None:
    await repos.checks.add(make_check("c-del"))
    option = Option(
        "o-del", "c-del", {}, "offer", "Bank X", date(2026, 10, 2), None, make_figures(), T0
    )
    await repos.options.add(option)
    await repos.recommendations.save(
        Recommendation(
            "c-del",
            "o-del",
            None,
            "why",
            Decimal("90000.00"),
            Decimal("2000.00"),
            T0,
        )
    )
    await repos.events.append("c-del", "message.user", {"text": "a"})
    await repos.awaiting.save(make_awaiting("a-del", "c-del"))

    await repos.checks.delete("c-del", "message.user", T0)

    with pytest.raises(CheckNotFoundError):
        await repos.checks.get(PERSON, "c-del")
    assert await repos.options.list("c-del") == []
    assert await repos.recommendations.latest("c-del") is None
    assert await repos.events.list("c-del", 0) == []
    assert await repos.awaiting.list("c-del") == []


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


async def test_checks_with_lists_the_persons_checks_holding_that_event(repos: Repos) -> None:
    for check_id, user_id in (("c-with-a", "with"), ("c-with-b", "with"), ("c-with-o", "other")):
        await repos.checks.add(make_check(check_id, user_id=user_id))
    await repos.events.append("c-with-a", "message.user", {"text": "a"})
    await repos.events.append("c-with-a", "message.user", {"text": "b"})
    await repos.events.append("c-with-b", "turn.status", {"status": "idle"})
    await repos.events.append("c-with-o", "message.user", {"text": "c"})

    assert await repos.events.checks_with("with", "message.user") == ["c-with-a"]


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


async def test_archive_stamps_the_check_and_restore_clears_it(repos: Repos) -> None:
    await repos.checks.add(make_check("c-arch"))

    await repos.checks.archive("c-arch", T0 + timedelta(hours=1))

    assert (await repos.checks.get(PERSON, "c-arch")).archived_at == T0 + timedelta(hours=1)
    with pytest.raises(CheckNotFoundError):
        await repos.checks.archive("c-missing", T0)

    await repos.checks.restore("c-arch")

    assert (await repos.checks.get(PERSON, "c-arch")).archived_at is None


async def test_clone_copies_the_loan_term_ceiling_and_finances_options_recommendation_and_events(
    repos: Repos,
) -> None:
    await repos.checks.add(make_check("c-src", "cloner"))
    await repos.checks.set_loan("c-src", LoanRequest("רכב", Decimal("150000.00")))
    await repos.checks.set_term("c-src", 60)
    await repos.checks.set_ceiling("c-src", Decimal("2500.50"), "stated")
    await repos.checks.set_finances("c-src", Finances(Decimal("15000.00"), Decimal("6000.00")))
    option = Option(
        "o-1", "c-src", {}, "offer", "Bank X", date(2026, 10, 2), None, make_figures(), T0
    )
    await repos.options.add(option)
    recommendation = Recommendation(
        "c-src",
        "o-1",
        None,
        "why",
        Decimal("90000.00"),
        Decimal("2000.00"),
        T0,
    )
    await repos.recommendations.save(recommendation)
    awaiting = make_awaiting("a-1", "c-src")
    await repos.awaiting.save(awaiting)
    before = datetime.now(UTC)
    await repos.events.append("c-src", "message.user", {"text": "a"})
    await repos.events.append("c-src", "check.archived", {})
    await repos.events.append("c-src", "message.assistant", {"text": "b"})
    source = await repos.checks.get("cloner", "c-src")
    clone = replace(source, id="c-copy", created_at=T0 + timedelta(hours=1))

    await repos.checks.clone("c-src", clone, ("check.archived",))

    stored = await repos.checks.get("cloner", "c-copy")
    assert stored == clone
    assert stored.loan == LoanRequest("רכב", Decimal("150000.00"))
    assert (stored.term_months, stored.payment_ceiling, stored.ceiling_source) == (
        60,
        Decimal("2500.50"),
        "stated",
    )
    assert stored.finances == Finances(Decimal("15000.00"), Decimal("6000.00"))
    assert await repos.options.list("c-copy") == [replace(option, check_id="c-copy")]
    assert await repos.recommendations.latest("c-copy") == replace(
        recommendation, check_id="c-copy"
    )
    assert await repos.awaiting.list("c-copy") == [replace(awaiting, check_id="c-copy")]
    copied = await repos.events.list("c-copy", 0)
    assert [(e.seq, e.type, dict(e.data)) for e in copied] == [
        (1, "message.user", {"text": "a"}),
        (2, "message.assistant", {"text": "b"}),
    ]
    assert (await repos.events.count_since("cloner", "message.user", before))[0] == 1
