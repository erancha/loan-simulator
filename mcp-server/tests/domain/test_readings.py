"""offer_readings() gives each loan an offer may mean, from its stated number or from its payment,
and leaves out a reading outside the priced ranges."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from loan_engine.domain.history import MarketHistory
from loan_engine.domain.readings import OfferReadings, offer_readings

CENT = Decimal("0.01")

# 120 flat months of a Bank of Israel rate of 3.25, so prime is 4.75.
HISTORY = MarketHistory(
    months=tuple(date(2010 + i // 12, i % 12 + 1, 1) for i in range(120)),
    boi_rate=(Decimal("3.25"),) * 120,
    monthly_inflation=(Decimal(0),) * 120,
    current_boi_rate=Decimal("3.25"),
    rate_as_of=date(2026, 10, 20),
    cpi_as_of=date(2026, 9, 1),
    consumer_rate=Decimal("7.9"),
    consumer_rate_month=date(2026, 8, 1),
    consumer_month_prime=Decimal("5.0"),
)


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def kinds(result: OfferReadings) -> list[str]:
    return [reading.kind for reading in result.readings]


def test_a_stated_number_gives_each_reading_with_its_first_payment() -> None:
    result = offer_readings(Decimal(45000), 60, Decimal(6), Decimal(972), True, HISTORY)
    assert kinds(result) == ["prime_margin", "prime_total", "fixed_unlinked", "fixed_linked"]
    assert [cents(r.first_payment) for r in result.readings] == [
        Decimal("972.81"),
        Decimal("869.98"),
        Decimal("869.98"),
        Decimal("871.41"),
    ]
    assert [r.total_rate for r in result.readings] == [Decimal("10.75"), 6, 6, 6]
    assert result.readings[1].track.prime_spread == Decimal("1.25")
    assert result.payment_rate is not None
    assert result.prime == Decimal("4.75")
    assert not any(r.approximate for r in result.readings)


def test_the_total_rate_reading_is_left_out_unless_asked() -> None:
    result = offer_readings(Decimal(45000), 60, Decimal(6), Decimal(972), False, HISTORY)
    assert kinds(result) == ["prime_margin", "fixed_unlinked", "fixed_linked"]


def test_maxs_offer_prices_prime_plus_6_45_at_934_01() -> None:
    result = offer_readings(Decimal(20000), 24, Decimal("6.45"), Decimal(934), True, HISTORY)
    by_kind = {r.kind: r for r in result.readings}
    assert cents(by_kind["prime_margin"].first_payment) == Decimal("934.01")
    assert by_kind["prime_margin"].total_rate == Decimal("11.20")
    assert cents(by_kind["fixed_unlinked"].first_payment) == Decimal("890.47")


def test_a_payment_alone_fixes_the_rate_of_each_type() -> None:
    result = offer_readings(Decimal(45000), 60, None, Decimal(969), False, HISTORY)
    assert result.payment_rate == Decimal("10.58")
    assert kinds(result) == ["fixed_unlinked", "prime_margin", "fixed_linked"]
    fixed, prime, linked = result.readings
    assert fixed.track.annual_rate == Decimal("10.58")
    assert prime.track.prime_spread == Decimal("5.83")
    assert linked.track.annual_rate == Decimal("10.58")
    assert linked.track.cpi_linked
    assert [r.approximate for r in result.readings] == [False, False, True]


def test_a_reading_outside_the_priced_ranges_is_left_out() -> None:
    high = offer_readings(Decimal(45000), 60, Decimal(25), None, True, HISTORY)
    assert kinds(high) == ["fixed_unlinked", "fixed_linked"]
    low = offer_readings(Decimal(45000), 60, Decimal("-0.5"), None, True, HISTORY)
    assert kinds(low) == ["prime_margin"]


@pytest.mark.parametrize(("principal", "payment"), [(100000, 969), (45000, 5000)])
def test_a_payment_no_rate_gives_has_no_reading(principal: int, payment: int) -> None:
    result = offer_readings(Decimal(principal), 60, None, Decimal(payment), False, HISTORY)
    assert result.payment_rate is None
    assert result.readings == ()


def test_neither_a_number_nor_a_payment_is_refused() -> None:
    with pytest.raises(ValueError, match="stated_rate.*monthly_payment"):
        offer_readings(Decimal(45000), 60, None, None, False, HISTORY)
