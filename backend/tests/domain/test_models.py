from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from loan_agent.domain.errors import GoalError, ProfileError
from loan_agent.domain.models import Check, Goal, OptionFigures, Profile

FULL = {
    "net_fixed_income": "20000.50",
    "variable_income": 1000,
    "variable_income_minimum": "400",
    "fixed_expenses": Decimal(9000),
    "existing_loan_payments": "0",
    "savings": "50000",
}


def figures(worst: Decimal | None) -> OptionFigures:
    return OptionFigures(
        first_payment=Decimal(1000),
        peak_payment=Decimal(1100),
        worst_peak_payment=worst,
        worst_start=None,
        worst_end=None,
        balloon_due=None,
        total_paid=Decimal(60000),
        rate_as_of=date(2026, 10, 1),
        cpi_as_of=date(2026, 9, 1),
    )


def test_profile_merge_sets_fields_and_reports_missing() -> None:
    profile = Profile().merged({"net_fixed_income": "20000.50", "savings": 5})

    assert profile.net_fixed_income == Decimal("20000.50")
    assert profile.savings == Decimal(5)
    assert profile.missing() == (
        "variable_income",
        "variable_income_minimum",
        "fixed_expenses",
        "existing_loan_payments",
    )


@pytest.mark.parametrize(
    ("update", "field"),
    [
        ({"colour": 1}, "colour"),
        ({"savings": "-1"}, "savings"),
        ({"fixed_expenses": 1.5}, "fixed_expenses"),
        ({"variable_income_minimum": "-1"}, "variable_income_minimum"),
        ({"variable_income": "abc"}, "variable_income"),
    ],
)
def test_profile_merge_rejects_unknown_and_negative_naming_field(
    update: dict[str, object], field: str
) -> None:
    with pytest.raises(ProfileError, match=field):
        Profile().merged(update)


def test_engine_profile_requires_complete_profile() -> None:
    profile = Profile().merged({"net_fixed_income": 1})

    with pytest.raises(ProfileError, match="variable_income, variable_income_minimum"):
        profile.engine_profile()


def test_engine_profile_sends_decimal_strings() -> None:
    assert Profile().merged(FULL).engine_profile() == {
        "net_fixed_income": "20000.50",
        "variable_income": "1000",
        "variable_income_minimum": "400",
        "fixed_expenses": "9000",
        "existing_loan_payments": "0",
    }


def test_goal_validation() -> None:
    Goal("car", Decimal(100000))
    with pytest.raises(GoalError, match="price"):
        Goal("car", Decimal(0))


def test_risk_payment_prefers_worst_window() -> None:
    assert figures(Decimal(1500)).risk_payment == Decimal(1500)
    assert figures(None).risk_payment == Decimal(1100)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="created_at"):
        Check("c", "u", datetime(2026, 1, 1), None, None)
    Check("c", "u", datetime(2026, 1, 1, tzinfo=UTC), None, None)


SNAPSHOT_AT = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def test_a_check_without_a_recommendation_is_never_stale() -> None:
    check = Check("c1", "1001", SNAPSHOT_AT, None, None)
    assert not check.is_stale(None)
    assert not check.is_stale(SNAPSHOT_AT + timedelta(days=1))


def test_a_check_is_stale_once_the_profile_is_saved_after_its_snapshot() -> None:
    check = Check("c1", "1001", SNAPSHOT_AT, None, SNAPSHOT_AT)
    assert not check.is_stale(SNAPSHOT_AT)
    assert check.is_stale(SNAPSHOT_AT + timedelta(microseconds=1))


def test_a_snapshot_without_a_saved_profile_is_a_broken_invariant() -> None:
    check = Check("c1", "1001", SNAPSHOT_AT, None, SNAPSHOT_AT)
    with pytest.raises(AssertionError):
        check.is_stale(None)


def test_option_figures_encode_as_json_ready_text_and_decode_back() -> None:
    worst = OptionFigures(
        first_payment=Decimal("1273.80"),
        peak_payment=Decimal("1376.53"),
        worst_peak_payment=Decimal("1482.61"),
        worst_start=date(2021, 5, 1),
        worst_end=date(2025, 4, 1),
        balloon_due=Decimal("32472.96"),
        total_paid=Decimal("96049.73"),
        rate_as_of=date(2026, 10, 26),
        cpi_as_of=date(2026, 9, 1),
    )

    assert worst.to_json() == {
        "first_payment": "1273.80",
        "peak_payment": "1376.53",
        "worst_peak_payment": "1482.61",
        "worst_start": "2021-05-01",
        "worst_end": "2025-04-01",
        "balloon_due": "32472.96",
        "total_paid": "96049.73",
        "rate_as_of": "2026-10-26",
        "cpi_as_of": "2026-09-01",
    }
    for value in (worst, figures(None)):
        assert OptionFigures.from_json(value.to_json()) == value


def test_minimum_is_not_missing_when_variable_income_is_zero() -> None:
    profile = Profile().merged({"net_fixed_income": "8000", "variable_income": "0"})
    assert "variable_income_minimum" not in profile.missing()
    assert "variable_income" not in profile.missing()


def test_minimum_is_missing_while_variable_income_is_unset_or_positive() -> None:
    assert "variable_income_minimum" in Profile().missing()
    positive = Profile().merged({"variable_income": "2500"})
    assert "variable_income_minimum" in positive.missing()


def test_minimum_needed_again_once_variable_income_is_positive() -> None:
    zero = Profile().merged({"variable_income": "0"})
    raised = zero.merged({"variable_income": "3000"})
    assert "variable_income_minimum" in raised.missing()


def test_engine_profile_sends_a_zero_minimum_when_variable_income_is_zero() -> None:
    profile = Profile().merged(
        {
            "net_fixed_income": "8000",
            "variable_income": "0",
            "fixed_expenses": "3000",
            "existing_loan_payments": "0",
            "savings": "10000",
        }
    )
    assert profile.engine_profile()["variable_income_minimum"] == "0"


def test_missing_lists_fields_from_money_at_hand_to_outgoings() -> None:
    assert Profile().missing() == (
        "savings",
        "net_fixed_income",
        "variable_income",
        "variable_income_minimum",
        "fixed_expenses",
        "existing_loan_payments",
    )


def test_minimum_above_variable_income_is_refused_naming_both() -> None:
    with pytest.raises(ProfileError, match="variable_income_minimum.*variable_income"):
        Profile().merged({"variable_income": "1000", "variable_income_minimum": "1001"})


def test_lowering_variable_income_below_the_stored_minimum_is_refused() -> None:
    profile = Profile().merged({"variable_income": "3000", "variable_income_minimum": "2000"})
    with pytest.raises(ProfileError, match="variable_income_minimum.*variable_income"):
        profile.merged({"variable_income": "1500"})
    assert profile.merged({"variable_income": "2000"}).variable_income == Decimal(2000)


def test_minimum_may_equal_variable_income() -> None:
    profile = Profile().merged({"variable_income": "1000", "variable_income_minimum": "1000"})
    assert profile.variable_income_minimum == Decimal(1000)
