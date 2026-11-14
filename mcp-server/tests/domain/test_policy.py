from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from pydantic import ValidationError

from loan_engine.domain.history import MarketHistory
from loan_engine.domain.models import Profile, Track
from loan_engine.domain.policy import (
    assess_affordability,
    largest_comfortable_loan,
    shortest_comfortable_offer_term,
    shortest_comfortable_term,
    size_loan,
    suggest_tracks,
)

CENT = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def make_profile(**overrides: object) -> Profile:
    fields: dict[str, object] = {
        "net_fixed_income": Decimal(8600),
        "variable_income": Decimal(5000),
        "variable_income_minimum": Decimal(0),
        "fixed_expenses": Decimal(5500),
        "existing_loan_payments": Decimal(0),
    }
    return Profile(**{**fields, **overrides})  # type: ignore[arg-type]


def test_reference_user() -> None:
    bounds = assess_affordability(make_profile())
    assert cents(bounds.payment_ceiling) == Decimal("1550.00")
    assert cents(bounds.min_cushion) == Decimal("11000.00")
    assert cents(bounds.counted_income) == Decimal("8600.00")
    assert bounds.reasons == ["ceiling_by_disposable_income"]


def test_variable_income_minimum_counted_in_full() -> None:
    bounds = assess_affordability(make_profile(variable_income_minimum=Decimal(2000)))
    assert cents(bounds.counted_income) == Decimal("10600.00")
    assert cents(bounds.payment_ceiling) == Decimal("2550.00")
    assert bounds.reasons == ["variable_income_minimum_counted", "ceiling_by_disposable_income"]


def test_minimum_equal_to_variable_income_counts_all_of_it() -> None:
    bounds = assess_affordability(make_profile(variable_income_minimum=Decimal(5000)))
    assert cents(bounds.counted_income) == Decimal("13600.00")


def test_ceiling_by_income_share() -> None:
    bounds = assess_affordability(make_profile(fixed_expenses=Decimal(1000)))
    assert cents(bounds.payment_ceiling) == Decimal("2580.00")
    assert bounds.reasons == ["ceiling_by_income_share"]


def test_existing_loans_deducted_and_floor_at_zero() -> None:
    deducted = assess_affordability(make_profile(existing_loan_payments=Decimal(500)))
    assert cents(deducted.payment_ceiling) == Decimal("1050.00")
    assert deducted.reasons == [
        "ceiling_by_disposable_income",
        "existing_loans_deducted",
    ]

    floored = assess_affordability(make_profile(existing_loan_payments=Decimal(2000)))
    assert floored.payment_ceiling == 0
    assert floored.reasons[-2:] == ["existing_loans_deducted", "no_room_for_payment"]


def test_no_variable_income_has_no_variable_reason() -> None:
    bounds = assess_affordability(make_profile(variable_income=Decimal(0)))
    assert bounds.reasons == ["ceiling_by_disposable_income"]


def test_minimum_above_variable_income_is_refused() -> None:
    with pytest.raises(ValidationError, match="variable_income_minimum.*variable_income"):
        make_profile(variable_income_minimum=Decimal(5001))


def test_size_loan_reference_user() -> None:
    sizing = size_loan(Decimal(35000), Decimal(15000), Decimal(11000))
    assert (sizing.loan_amount, sizing.savings_used) == (31000, 4000)
    assert (sizing.cushion_kept, sizing.spare_savings) == (11000, 0)


def test_size_loan_savings_below_cushion_uses_none() -> None:
    sizing = size_loan(Decimal(35000), Decimal(9000), Decimal(11000))
    assert (sizing.loan_amount, sizing.savings_used) == (35000, 0)
    assert (sizing.cushion_kept, sizing.spare_savings) == (9000, 0)


def test_size_loan_covered_returns_zero_and_spare() -> None:
    sizing = size_loan(Decimal(10000), Decimal(15000), Decimal(2000))
    assert (sizing.loan_amount, sizing.savings_used) == (0, 10000)
    assert (sizing.cushion_kept, sizing.spare_savings) == (2000, 3000)


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


@pytest.mark.parametrize(
    ("ceiling", "term"),
    [
        # 31,000 at 7.9% over 18 months is 1,831.93 a month; 90% of 2,036 holds it, of 2,035 not.
        (Decimal(2036), 18),
        (Decimal(2035), 24),
        (Decimal(1600), 24),
    ],
)
def test_the_shortest_term_keeps_the_payment_within_ninety_percent_of_the_ceiling(
    ceiling: Decimal, term: int
) -> None:
    assert shortest_comfortable_term(Decimal(31000), ceiling, FLAT) == term


def test_no_term_fits_a_ceiling_too_low_for_the_loan() -> None:
    assert shortest_comfortable_term(Decimal(31000), Decimal(300), FLAT) is None


def test_the_largest_comfortable_loan_is_the_last_whole_thousand_that_fits() -> None:
    ceiling = Decimal(2000)
    largest = largest_comfortable_loan(ceiling, FLAT)

    assert largest is not None and largest % 1000 == 0
    assert shortest_comfortable_term(largest, ceiling, FLAT) is not None
    assert shortest_comfortable_term(largest + 1000, ceiling, FLAT) is None


def test_a_ceiling_below_the_smallest_loan_carries_none() -> None:
    assert largest_comfortable_loan(Decimal(100), FLAT) is None


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
    # 32,000 at 5.25% over 24 months is 1,407 a month, within 90% of 2,000; 18 months is 1,853.
    assert shortest_comfortable_offer_term(_offer(84), Decimal(2000), FLAT) == 24


def test_an_offer_also_tries_its_own_maximum_between_the_steps() -> None:
    # 22 months is 1,529 a month, within 90% of 2,000; the steps below it reach only 18.
    assert shortest_comfortable_offer_term(_offer(22), Decimal(2000), FLAT) == 22


def test_no_term_of_an_offer_fits_a_ceiling_too_low_for_it() -> None:
    assert shortest_comfortable_offer_term(_offer(84), Decimal(300), FLAT) is None


def test_a_rate_rise_in_history_lengthens_the_term_through_the_prime_track() -> None:
    rising = ten_years([Decimal(i) / 4 for i in range(120)])
    flat_term = shortest_comfortable_term(Decimal(31000), Decimal(1600), FLAT)
    rising_term = shortest_comfortable_term(Decimal(31000), Decimal(1600), rising)
    assert flat_term is not None and rising_term is not None
    assert rising_term > flat_term
