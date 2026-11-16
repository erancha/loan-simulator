from decimal import Decimal

from loan_engine.domain.affordability import assess_affordability
from loan_engine.domain.models import Profile


def make_profile(income: int, expenses: int) -> Profile:
    return Profile(net_fixed_income=Decimal(income), fixed_expenses=Decimal(expenses))


def test_reference_user_ceiling() -> None:
    bounds = assess_affordability(make_profile(12000, 6000))
    assert bounds.payment_ceiling == Decimal(3000)
    assert bounds.counted_income == Decimal(12000)
    assert bounds.reasons == ["ceiling_by_disposable_income"]


def test_bounds_carry_both_caps_and_their_shares() -> None:
    bounds = assess_affordability(make_profile(10000, 7000))
    assert (bounds.income_share, bounds.ceiling_by_income_share) == (Decimal("0.30"), 3000)
    assert (bounds.disposable_share, bounds.ceiling_by_disposable_income) == (Decimal("0.50"), 1500)
    assert bounds.payment_ceiling == 1500


def test_ceiling_by_income_share() -> None:
    bounds = assess_affordability(make_profile(8600, 1000))
    assert bounds.payment_ceiling == Decimal("2580.00")
    assert bounds.reasons == ["ceiling_by_income_share"]


def test_expenses_above_income_leave_no_room() -> None:
    bounds = assess_affordability(make_profile(5000, 6000))
    assert bounds.payment_ceiling == 0
    assert bounds.reasons[-1] == "no_room_for_payment"
