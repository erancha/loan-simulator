from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from loan_agent.domain.errors import FinancesError, LoanError
from loan_agent.domain.models import (
    CAR_PURPOSE,
    CAR_TERM_MONTHS,
    FIRST_PAYMENT_TARGET,
    Check,
    Finances,
    LoanRequest,
    OptionFigures,
    Recommendation,
)


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


NOW = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def make_check(**overrides: object) -> Check:
    values: dict[str, object] = {
        "id": "c1",
        "user_id": "1001",
        "created_at": NOW,
        "loan": None,
        "term_months": None,
        "payment_ceiling": None,
        "ceiling_source": None,
        "finances": Finances(),
    }
    return Check(**{**values, **overrides})  # type: ignore[arg-type]


def test_finances_missing_lists_both_until_told() -> None:
    finances = Finances()
    assert finances.missing() == ("net_fixed_income", "fixed_expenses")

    finances = finances.merged({"net_fixed_income": "20000.50"})
    assert finances.net_fixed_income == Decimal("20000.50")
    assert finances.missing() == ("fixed_expenses",)
    assert finances.merged({"fixed_expenses": 9000}).missing() == ()


@pytest.mark.parametrize(
    ("update", "field"),
    [
        ({"colour": 1}, "colour"),
        ({"fixed_expenses": "-1"}, "fixed_expenses"),
        ({"fixed_expenses": 1.5}, "fixed_expenses"),
        ({"net_fixed_income": "abc"}, "net_fixed_income"),
    ],
)
def test_finances_refuse_a_negative_amount(update: dict[str, object], field: str) -> None:
    with pytest.raises(FinancesError, match=field):
        Finances().merged(update)


def test_engine_profile_refuses_incomplete_finances() -> None:
    with pytest.raises(FinancesError, match="fixed_expenses"):
        Finances(net_fixed_income=Decimal(1)).engine_profile()


def test_engine_profile_sends_decimal_strings() -> None:
    finances = Finances().merged({"net_fixed_income": "20000.50", "fixed_expenses": Decimal(9000)})
    assert finances.engine_profile() == {"net_fixed_income": "20000.50", "fixed_expenses": "9000"}


def test_a_loan_request_refuses_a_zero_amount() -> None:
    assert LoanRequest(CAR_PURPOSE, Decimal(100000)).amount == Decimal(100000)
    assert LoanRequest(None, Decimal(1)).purpose is None
    with pytest.raises(LoanError, match="amount"):
        LoanRequest(CAR_PURPOSE, Decimal(0))


def test_the_term_card_defaults() -> None:
    assert (CAR_PURPOSE, CAR_TERM_MONTHS, FIRST_PAYMENT_TARGET) == ("רכב", 60, Decimal(1000))


def test_a_ceiling_needs_its_source() -> None:
    with pytest.raises(AssertionError):
        make_check(payment_ceiling=Decimal(2000))
    with pytest.raises(AssertionError):
        make_check(ceiling_source="stated")
    check = make_check(payment_ceiling=Decimal(2000), ceiling_source="stated")
    assert check.payment_ceiling == Decimal(2000)


def test_a_recommendation_without_a_ceiling_is_unchecked() -> None:
    def recommendation(ceiling: Decimal | None) -> Recommendation:
        return Recommendation("c1", "o1", None, "why", Decimal(100000), ceiling, NOW)

    assert not recommendation(None).checked
    assert recommendation(Decimal(2000)).checked


def test_risk_payment_prefers_worst_window() -> None:
    assert figures(Decimal(1500)).risk_payment == Decimal(1500)
    assert figures(None).risk_payment == Decimal(1100)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="created_at"):
        make_check(created_at=datetime(2026, 1, 1))
    make_check(created_at=datetime(2026, 1, 1, tzinfo=UTC))


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
