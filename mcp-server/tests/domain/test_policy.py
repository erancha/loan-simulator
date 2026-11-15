from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from loan_engine.domain.assumptions import LOAN_STEP
from loan_engine.domain.history import MarketHistory, simulate
from loan_engine.domain.limits import MAX_TERM
from loan_engine.domain.models import Track
from loan_engine.domain.policy import (
    largest_comfortable_loan,
    proposed_offer_term,
    proposed_term,
    shortest_comfortable_offer_term,
    shortest_comfortable_term,
    suggest_tracks,
)

CENT = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def test_suggest_tracks_from_published_average() -> None:
    history = MarketHistory(
        months=(),
        boi_rate=(),
        monthly_inflation=(),
        current_boi_rate=Decimal("4.5"),
        rate_as_of=date(2026, 10, 20),
        cpi_as_of=date(2026, 9, 1),
        consumer_rate=Decimal("7.9"),
        consumer_rate_month=date(2026, 8, 1),
        consumer_month_prime=Decimal("5.0"),
    )
    fixed, prime = suggest_tracks(Decimal(31000), 48, history)
    assert (fixed.rate_kind, fixed.annual_rate, fixed.prime_spread) == (
        "fixed",
        Decimal("7.9"),
        None,
    )
    assert (prime.rate_kind, prime.annual_rate, prime.prime_spread) == (
        "prime",
        None,
        Decimal("2.9"),
    )
    for track in (fixed, prime):
        assert (track.principal, track.term_months) == (31000, 48)
        assert not track.cpi_linked
        assert track.method == "spitzer"
        assert track.one_time_fee == 0 and track.monthly_fee == 0


def ten_years(boi: list[Decimal]) -> MarketHistory:
    """120 months of the given Bank of Israel rates, today's rate 3.5, so the suggested prime
    track starts at 7.9%, like the fixed one."""
    return MarketHistory(
        months=tuple(date(2010 + i // 12, i % 12 + 1, 1) for i in range(120)),
        boi_rate=tuple(boi),
        monthly_inflation=(Decimal(0),) * 120,
        current_boi_rate=Decimal("3.5"),
        rate_as_of=date(2026, 10, 20),
        cpi_as_of=date(2026, 9, 1),
        consumer_rate=Decimal("7.9"),
        consumer_rate_month=date(2026, 8, 1),
        consumer_month_prime=Decimal("5.0"),
    )


FLAT = ten_years([Decimal("3.5")] * 120)


def _peak(principal: Decimal, term: int, history: MarketHistory) -> Decimal:
    return max(
        (o.base.max_payment if o.worst is None else o.worst.max_payment)
        for o in (simulate(t, history) for t in suggest_tracks(principal, term, history))
    )


def test_the_shortest_term_keeps_the_worst_payment_within_the_ceiling() -> None:
    rising = ten_years([Decimal(i) / 4 for i in range(120)])
    ceiling = Decimal(1600)
    term = shortest_comfortable_term(Decimal(31000), ceiling, rising)

    assert term is not None
    assert _peak(Decimal(31000), term, rising) <= ceiling
    assert _peak(Decimal(31000), term - 6, rising) > ceiling


def test_any_track_takes_the_first_term_where_one_track_fits() -> None:
    rising = ten_years([Decimal(i) / 4 for i in range(120)])
    principal, ceiling = Decimal(50000), Decimal(800)

    assert shortest_comfortable_term(principal, ceiling, rising) is None
    assert shortest_comfortable_term(principal, ceiling, rising, any_track=True) == MAX_TERM


def test_no_term_fits_a_ceiling_too_low_for_the_loan() -> None:
    assert shortest_comfortable_term(Decimal(31000), Decimal(300), FLAT) is None


def test_the_largest_loan_fits_at_the_given_term() -> None:
    rising = ten_years([Decimal(i) / 4 for i in range(120)])
    ceiling = Decimal(2000)
    largest = largest_comfortable_loan(ceiling, 60, rising)

    assert largest is not None and largest % LOAN_STEP == 0
    assert _fits_on_one_track(largest, ceiling, 60, rising)
    assert not _fits_on_one_track(largest + LOAN_STEP, ceiling, 60, rising)


def _fits_on_one_track(
    principal: Decimal, ceiling: Decimal, term: int, history: MarketHistory
) -> bool:
    return any(
        (o.base.max_payment if o.worst is None else o.worst.max_payment) <= ceiling
        for o in (simulate(t, history) for t in suggest_tracks(principal, term, history))
    )


def test_a_ceiling_below_the_smallest_loan_carries_none() -> None:
    assert largest_comfortable_loan(Decimal(100), 60, FLAT) is None


def test_max_term_is_84() -> None:
    assert MAX_TERM == 84


def _offer(term_months: int) -> Track:
    return Track(
        principal=Decimal(32000),
        term_months=term_months,
        rate_kind="fixed",
        annual_rate=Decimal("5.25"),
        cpi_linked=False,
        method="spitzer",
    )


def test_an_offer_up_to_a_long_term_takes_the_shortest_comfortable_term() -> None:
    # 32,000 at 5.25% over 24 months is 1,407 a month, within 1,500; 18 months is 1,853.
    assert shortest_comfortable_offer_term(_offer(84), Decimal(1500), FLAT) == 24


def test_an_offer_also_tries_its_own_maximum_between_the_steps() -> None:
    # 22 months is 1,529 a month, within 1,600; the steps below it reach only 18.
    assert shortest_comfortable_offer_term(_offer(22), Decimal(1600), FLAT) == 22


def test_no_term_of_an_offer_fits_a_ceiling_too_low_for_it() -> None:
    assert shortest_comfortable_offer_term(_offer(84), Decimal(300), FLAT) is None


def test_a_rate_rise_in_history_lengthens_the_term_through_the_prime_track() -> None:
    rising = ten_years([Decimal(i) / 4 for i in range(120)])
    flat_term = shortest_comfortable_term(Decimal(31000), Decimal(1000), FLAT)
    rising_term = shortest_comfortable_term(Decimal(31000), Decimal(1000), rising)
    assert flat_term is not None and rising_term is not None
    assert rising_term > flat_term


def _first_payment(principal: Decimal, term: int, history: MarketHistory) -> Decimal:
    return max(
        simulate(t, history).base.first_payment for t in suggest_tracks(principal, term, history)
    )


def test_the_proposed_term_is_the_first_under_the_limit() -> None:
    principal, limit = Decimal(31000), Decimal(1000)
    term = proposed_term(principal, limit, FLAT)

    assert _first_payment(principal, term, FLAT) < limit
    assert _first_payment(principal, term - 6, FLAT) >= limit


def test_no_term_under_the_limit_proposes_the_longest() -> None:
    assert proposed_term(Decimal(200000), Decimal(500), FLAT) == MAX_TERM


def test_an_offer_proposes_its_own_maximum_when_nothing_is_under_the_limit() -> None:
    assert proposed_offer_term(_offer(22), Decimal(300), FLAT) == 22


def test_an_offer_proposes_the_first_term_under_the_limit() -> None:
    assert proposed_offer_term(_offer(84), Decimal(1500), FLAT) == 24
