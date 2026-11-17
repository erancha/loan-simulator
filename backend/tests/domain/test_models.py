import dataclasses
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from loan_agent.domain.errors import FinancesError, LoanError
from loan_agent.domain.models import (
    FIRST_PAYMENT_TARGET,
    AwaitingOffer,
    Check,
    Finances,
    LoanRequest,
    Option,
    OptionFigures,
    OptionPrice,
    OptionSource,
    Reading,
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
        price=None,
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
    ("finances", "has_figures"),
    [
        (Finances(), False),
        (Finances(net_fixed_income=Decimal(1)), True),
        (Finances(fixed_expenses=Decimal(0)), True),
        (Finances(Decimal(1), Decimal(2)), True),
    ],
)
def test_finances_have_figures_once_any_is_told(finances: Finances, has_figures: bool) -> None:
    assert finances.has_figures() is has_figures


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
    assert LoanRequest("רכב", Decimal(100000)).amount == Decimal(100000)
    assert LoanRequest(None, Decimal(1)).purpose is None
    with pytest.raises(LoanError, match="amount"):
        LoanRequest("רכב", Decimal(0))


def test_the_term_card_assumes_a_first_payment_of_1000() -> None:
    assert FIRST_PAYMENT_TARGET == Decimal(1000)


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
        price=OptionPrice(
            rate_today=Decimal("4.9"),
            against_market=None,
            market_rate=Decimal("7.9"),
            market_rate_month=date(2026, 8, 1),
        ),
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
        "price": {
            "rate_today": "4.9",
            "against_market": None,
            "market_rate": "7.9",
            "market_rate_month": "2026-08-01",
        },
    }
    for value in (worst, figures(None)):
        assert OptionFigures.from_json(value.to_json()) == value


def test_option_figures_stored_before_the_engine_priced_rates_decode_without_a_price() -> None:
    stored = {key: value for key, value in figures(None).to_json().items() if key != "price"}
    assert OptionFigures.from_json(stored).price is None


def test_an_offer_costs_its_total_minus_the_principal() -> None:
    option = Option(
        id="o1",
        check_id="c1",
        loan={"tracks": [{"principal": "45000", "term_months": 60}]},
        source="offer",
        lender="לאומי",
        offer_date=None,
        max_term_months=None,
        summary=dataclasses.replace(figures(None), total_paid=Decimal("58368.40")),
        created_at=NOW,
    )
    assert option.principal == Decimal(45000)
    assert option.interest_cost == Decimal("13368.40")


@pytest.mark.parametrize(
    ("term", "source", "track_term", "for_term"),
    [
        (None, "example", 48, True),
        (60, "example", 48, False),
        (60, "example", 60, True),
        (60, "offer", 48, True),
    ],
)
def test_an_option_is_for_the_term_when_an_offer_or_an_example_of_it(
    term: int | None, source: OptionSource, track_term: int, for_term: bool
) -> None:
    option = Option(
        id="o1",
        check_id="c1",
        loan={"tracks": [{"principal": "45000", "term_months": track_term}]},
        source=source,
        lender=None,
        offer_date=None,
        max_term_months=None,
        summary=figures(None),
        created_at=NOW,
    )
    assert option.for_term(term) is for_term


LINKED_READING = Reading(
    kind="fixed_linked",
    track={"principal": "45000", "term_months": 60, "rate_kind": "fixed", "cpi_linked": True},
    first_payment=Decimal("970.61"),
    total_rate=Decimal("10.58"),
    approximate=True,
)


def test_a_reading_encodes_as_json_ready_text_and_decodes_back() -> None:
    encoded = LINKED_READING.to_json()

    assert encoded == {
        "kind": "fixed_linked",
        "track": dict(LINKED_READING.track),
        "first_payment": "970.61",
        "total_rate": "10.58",
        "approximate": True,
    }
    assert Reading.from_json(encoded) == LINKED_READING


def test_a_reading_of_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="prime_or_fixed"):
        Reading.from_json({**LINKED_READING.to_json(), "kind": "prime_or_fixed"})


def test_an_awaiting_offer_with_a_naive_created_at_is_refused() -> None:
    with pytest.raises(ValueError, match="created_at"):
        AwaitingOffer(
            id="a1",
            check_id="c1",
            lender="בנק הפועלים",
            amount=Decimal(45000),
            term_months=60,
            stated_rate=None,
            monthly_payment=Decimal(969),
            payment_rate=Decimal("10.58"),
            type_words=(),
            readings=(LINKED_READING,),
            likely=None,
            prime=Decimal("4.75"),
            rate_as_of=date(2026, 10, 20),
            created_at=datetime(2026, 10, 1, 8, 0),
        )
