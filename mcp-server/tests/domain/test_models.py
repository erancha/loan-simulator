"""The input models refuse a track, loan, profile or scenario outside the limits the engine prices,
with an error that names the field."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from loan_engine.domain.models import DEFAULT_SCENARIO, Loan, Profile, Scenario, Track


def make_track(**overrides: object) -> Track:
    fields: dict[str, object] = {
        "principal": Decimal(25000),
        "term_months": 48,
        "rate_kind": "fixed",
        "annual_rate": Decimal("6.5"),
        "prime_spread": None,
        "cpi_linked": False,
        "method": "spitzer",
    }
    return Track(**{**fields, **overrides})  # type: ignore[arg-type]


def test_fixed_track_requires_annual_rate_and_rejects_spread() -> None:
    with pytest.raises(ValidationError, match="annual_rate"):
        make_track(annual_rate=None)
    with pytest.raises(ValidationError, match="prime_spread"):
        make_track(prime_spread=Decimal("1.5"))


def test_prime_track_requires_spread_and_rejects_annual_rate() -> None:
    prime = {"rate_kind": "prime", "annual_rate": None, "prime_spread": Decimal("1.5")}
    assert make_track(**prime).prime_spread == Decimal("1.5")
    with pytest.raises(ValidationError, match="prime_spread"):
        make_track(**{**prime, "prime_spread": None})
    with pytest.raises(ValidationError, match="annual_rate"):
        make_track(**{**prime, "annual_rate": Decimal("6.5")})


def test_balloon_amount_must_be_below_principal() -> None:
    balloon = {"method": "balloon", "principal": Decimal(25000)}
    assert make_track(**balloon, balloon_amount=Decimal(24999)).balloon_amount == 24999
    with pytest.raises(ValidationError, match="balloon_amount"):
        make_track(**balloon, balloon_amount=Decimal(25000))


def test_balloon_method_requires_balloon_amount() -> None:
    for amount in (None, Decimal(0)):
        fields = {} if amount is None else {"balloon_amount": amount}
        with pytest.raises(ValidationError, match="balloon_amount must be above 0"):
            make_track(method="balloon", **fields)


def test_rates_are_bounded() -> None:
    for rate in ("-0.01", "30.01"):
        with pytest.raises(ValidationError, match="annual_rate"):
            make_track(annual_rate=Decimal(rate))
    for rate in ("0", "30"):
        assert make_track(annual_rate=Decimal(rate)).annual_rate == Decimal(rate)
    prime = {"rate_kind": "prime", "annual_rate": None}
    for spread in ("-1.51", "20.01"):
        with pytest.raises(ValidationError, match="prime_spread"):
            make_track(**prime, prime_spread=Decimal(spread))
    for spread in ("-1.5", "20"):
        assert make_track(**prime, prime_spread=Decimal(spread)).prime_spread == Decimal(spread)


def test_balloon_amount_only_with_balloon_method() -> None:
    with pytest.raises(ValidationError, match="balloon_amount"):
        make_track(method="spitzer", balloon_amount=Decimal(1000))


def test_term_and_principal_limits() -> None:
    for months in (5, 85):
        with pytest.raises(ValidationError, match="term_months"):
            make_track(term_months=months)
    for months in (6, 84):
        assert make_track(term_months=months).term_months == months
    for amount in (9999, 10000001):
        with pytest.raises(ValidationError, match="principal"):
            Loan(tracks=[make_track(principal=Decimal(amount))])
    for amount in (10000, 10000000):
        assert Loan(tracks=[make_track(principal=Decimal(amount))]).principal == amount
    with pytest.raises(ValidationError, match="principal"):
        make_track(principal=Decimal(0))
    with pytest.raises(ValidationError, match="principal"):
        make_track(principal=Decimal(10000001))


def test_fees_and_profile_amounts_are_non_negative() -> None:
    for field in ("one_time_fee", "monthly_fee"):
        with pytest.raises(ValidationError, match=field):
            make_track(**{field: Decimal(-1)})
    profile = {"net_fixed_income": Decimal(15000), "fixed_expenses": Decimal(8000)}
    assert Profile(**profile).net_fixed_income == 15000  # type: ignore[arg-type]
    for field in ("net_fixed_income", "fixed_expenses"):
        with pytest.raises(ValidationError, match=field):
            Profile(**{**profile, field: Decimal(-1)})  # type: ignore[arg-type]


def test_loan_principal_sums_tracks() -> None:
    loan = Loan(tracks=[make_track(principal=Decimal(20000)), make_track(principal=Decimal(30000))])
    assert loan.principal == Decimal(50000)
    with pytest.raises(ValidationError, match="tracks"):
        Loan(tracks=[])


def test_omitted_rate_fields_default_to_none() -> None:
    common = {
        "principal": Decimal(25000),
        "term_months": 48,
        "cpi_linked": False,
        "method": "spitzer",
    }
    prime = Track(**common, rate_kind="prime", prime_spread=Decimal("1.5"))  # type: ignore[arg-type]
    fixed = Track(**common, rate_kind="fixed", annual_rate=Decimal("6.5"))  # type: ignore[arg-type]
    assert prime.annual_rate is None
    assert fixed.prime_spread is None


def test_multi_track_loan_principal_limits_apply_to_the_sum() -> None:
    for amounts in ((4000, 5000), (6000000, 4000001)):
        tracks = [make_track(principal=Decimal(amount)) for amount in amounts]
        with pytest.raises(ValidationError, match="principal"):
            Loan(tracks=tracks)
    assert Loan(tracks=[make_track(principal=Decimal(a)) for a in (4000, 6000)]).principal == 10000


def test_a_scenario_defaults_to_two_percent_cpi_and_a_flat_prime() -> None:
    assert Scenario() == DEFAULT_SCENARIO
    assert (DEFAULT_SCENARIO.cpi_per_year, DEFAULT_SCENARIO.prime_per_year) == (2, 0)


@pytest.mark.parametrize(
    ("field", "value"),
    [("cpi_per_year", -6), ("cpi_per_year", 21), ("prime_per_year", -6), ("prime_per_year", 6)],
)
def test_a_scenario_refuses_values_out_of_range(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match=field):
        Scenario.model_validate({field: value})


def test_a_scenario_takes_a_movement_as_a_rise_or_as_the_last_years_not_both() -> None:
    with pytest.raises(ValidationError, match="cpi_per_year or cpi_like_last_years"):
        Scenario(cpi_per_year=Decimal(5), cpi_like_last_years=3)
    assert Scenario(prime_like_last_years=10).prime_like_last_years == 10
    with pytest.raises(ValidationError, match="prime_like_last_years"):
        Scenario(prime_like_last_years=11)
