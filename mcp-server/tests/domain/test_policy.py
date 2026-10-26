from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from loan_engine.domain.history import MarketHistory
from loan_engine.domain.models import Profile
from loan_engine.domain.policy import assess_affordability, size_loan, suggest_tracks

CENT = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def make_profile(**overrides: object) -> Profile:
    fields: dict[str, object] = {
        "net_fixed_income": Decimal(8600),
        "variable_income": Decimal(5000),
        "variable_income_stable": False,
        "fixed_expenses": Decimal(5500),
        "existing_loan_payments": Decimal(0),
    }
    return Profile(**{**fields, **overrides})  # type: ignore[arg-type]


def test_reference_user() -> None:
    bounds = assess_affordability(make_profile())
    assert cents(bounds.payment_ceiling) == Decimal("1550.00")
    assert cents(bounds.min_cushion) == Decimal("11000.00")
    assert cents(bounds.counted_income) == Decimal("8600.00")
    assert bounds.reasons == ["variable_income_excluded", "ceiling_by_disposable_income"]


def test_stable_variable_half_counted() -> None:
    bounds = assess_affordability(make_profile(variable_income_stable=True))
    assert cents(bounds.counted_income) == Decimal("11100.00")
    assert cents(bounds.payment_ceiling) == Decimal("2800.00")
    assert bounds.reasons == ["variable_income_half_counted", "ceiling_by_disposable_income"]


def test_ceiling_by_income_share() -> None:
    bounds = assess_affordability(make_profile(fixed_expenses=Decimal(1000)))
    assert cents(bounds.payment_ceiling) == Decimal("2580.00")
    assert bounds.reasons == ["variable_income_excluded", "ceiling_by_income_share"]


def test_existing_loans_deducted_and_floor_at_zero() -> None:
    deducted = assess_affordability(make_profile(existing_loan_payments=Decimal(500)))
    assert cents(deducted.payment_ceiling) == Decimal("1050.00")
    assert deducted.reasons == [
        "variable_income_excluded",
        "ceiling_by_disposable_income",
        "existing_loans_deducted",
    ]

    floored = assess_affordability(make_profile(existing_loan_payments=Decimal(2000)))
    assert floored.payment_ceiling == 0
    assert floored.reasons[-2:] == ["existing_loans_deducted", "no_room_for_payment"]


def test_no_variable_income_has_no_variable_reason() -> None:
    bounds = assess_affordability(make_profile(variable_income=Decimal(0)))
    assert bounds.reasons == ["ceiling_by_disposable_income"]


def test_size_loan_reference_user() -> None:
    sizing = size_loan(Decimal(55000), Decimal(20000), Decimal(15000), Decimal(11000))
    assert (sizing.loan_amount, sizing.savings_used) == (31000, 4000)
    assert (sizing.cushion_kept, sizing.spare_savings) == (11000, 0)


def test_size_loan_savings_below_cushion_uses_none() -> None:
    sizing = size_loan(Decimal(55000), Decimal(20000), Decimal(9000), Decimal(11000))
    assert (sizing.loan_amount, sizing.savings_used) == (35000, 0)
    assert (sizing.cushion_kept, sizing.spare_savings) == (9000, 0)


def test_size_loan_covered_returns_zero_and_spare() -> None:
    sizing = size_loan(Decimal(30000), Decimal(20000), Decimal(15000), Decimal(2000))
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
