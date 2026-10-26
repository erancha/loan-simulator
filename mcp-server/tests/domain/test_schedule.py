from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

import pytest

from loan_engine.domain.models import Track
from loan_engine.domain.schedule import schedule

CENT = Decimal("0.01")
ZEROS = [Decimal(0)] * 96


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def make_track(**overrides: object) -> Track:
    fields: dict[str, object] = {
        "principal": Decimal(25000),
        "term_months": 48,
        "rate_kind": "fixed",
        "annual_rate": Decimal("7.75"),
        "prime_spread": None,
        "cpi_linked": False,
        "method": "spitzer",
    }
    return Track(**{**fields, **overrides})  # type: ignore[arg-type]


def flat(rate: str, months: int) -> list[Decimal]:
    return [Decimal(rate)] * months


def test_spitzer_flat_rate() -> None:
    result = schedule(make_track(), flat("7.75", 48), ZEROS[:48])
    assert {cents(row.payment) for row in result.rows} == {Decimal("607.39")}
    assert cents(result.total_paid) == Decimal("29154.89")
    assert result.rows[-1].balance == 0


def test_equal_principal_first_payment() -> None:
    result = schedule(make_track(method="equal_principal"), flat("7.75", 48), ZEROS[:48])
    assert cents(result.first_payment) == Decimal("682.29")
    payments = [row.payment for row in result.rows]
    assert all(a > b for a, b in pairwise(payments))
    assert result.max_payment == result.first_payment
    assert result.rows[-1].balance == 0


def test_balloon() -> None:
    track = make_track(method="balloon", balloon_amount=Decimal(10000))
    result = schedule(track, flat("7.75", 48), ZEROS[:48])
    assert {cents(row.payment) for row in result.rows[:-1]} == {Decimal("429.02")}
    assert cents(result.rows[-1].payment) == Decimal("429.02") + 10000
    assert result.rows[-1].balance == 0
    assert cents(result.max_payment) == Decimal("429.02")
    assert result.balloon_due is not None and cents(result.balloon_due) == 10000
    assert result.total_paid == sum(row.payment for row in result.rows)


def test_track_without_balloon_has_no_balloon_due() -> None:
    for method in ("spitzer", "equal_principal"):
        result = schedule(make_track(method=method), flat("7.75", 48), ZEROS[:48])
        assert result.balloon_due is None
        assert result.max_payment == max(row.payment for row in result.rows)


def test_zero_rate() -> None:
    track = make_track(principal=Decimal(12000), term_months=24, annual_rate=Decimal(0))
    result = schedule(track, flat("0", 24), ZEROS[:24])
    assert {cents(row.payment) for row in result.rows} == {Decimal("500.00")}
    assert result.rows[-1].balance == 0


def test_rate_change_recomputes_payment() -> None:
    track = make_track(rate_kind="prime", annual_rate=None, prime_spread=Decimal(0), term_months=36)
    result = schedule(track, flat("6.25", 12) + flat("9.25", 24), ZEROS[:36])
    payments = [cents(row.payment) for row in result.rows]
    assert len(set(payments[:12])) == 1
    assert payments[12] > payments[11]
    assert len(set(payments[12:])) == 1
    assert result.rows[-1].balance == 0


def test_cpi_linked_balance_indexed() -> None:
    linked = make_track(cpi_linked=True, annual_rate=Decimal("4.5"))
    unlinked = make_track(annual_rate=Decimal("4.5"))
    inflation = [Decimal("0.005")] * 48
    payments = [row.payment for row in schedule(linked, flat("4.5", 48), inflation).rows]
    assert all(a < b for a, b in pairwise(payments))
    with_zero = schedule(linked, flat("4.5", 48), ZEROS[:48])
    assert with_zero == schedule(unlinked, flat("4.5", 48), ZEROS[:48])


def test_cpi_linked_balloon_is_indexed() -> None:
    track = make_track(cpi_linked=True, method="balloon", balloon_amount=Decimal(10000))
    result = schedule(track, flat("7.75", 48), [Decimal("0.005")] * 48)
    assert result.rows[-1].payment > 10000 * Decimal("1.005") ** 48
    assert result.rows[-1].balance == 0
    assert result.balloon_due is not None
    assert cents(result.balloon_due) == cents(10000 * Decimal("1.005") ** 48)
    assert result.max_payment == result.rows[-1].payment - result.balloon_due


def test_unlinked_track_ignores_inflation() -> None:
    result = schedule(make_track(), flat("7.75", 48), [Decimal("0.5")] * 48)
    assert cents(result.first_payment) == Decimal("607.39")


def test_fees() -> None:
    track = make_track(monthly_fee=Decimal(10), one_time_fee=Decimal(300))
    result = schedule(track, flat("7.75", 48), ZEROS[:48])
    assert {cents(row.payment) for row in result.rows} == {Decimal("617.39")}
    assert cents(result.total_paid) == Decimal("29154.89") + 480 + 300


def test_rates_length_must_match_term() -> None:
    with pytest.raises(ValueError, match="annual_rates"):
        schedule(make_track(), flat("7.75", 47), ZEROS[:48])


def test_inflation_length_must_match_term_for_linked_track() -> None:
    with pytest.raises(ValueError, match="monthly_inflation"):
        schedule(make_track(cpi_linked=True), flat("7.75", 48), ZEROS[:47])
