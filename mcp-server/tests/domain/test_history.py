import dataclasses
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from loan_engine.domain.assumptions import BASE_ANNUAL_INFLATION, HISTORY_MONTHS, PRIME_MARGIN
from loan_engine.domain.history import MarketHistory, NoHistoryWindowError, rate_today, simulate
from loan_engine.domain.models import Track
from loan_engine.domain.schedule import Schedule, schedule

SPREAD = Decimal("1.0")
BASE_MONTHLY_INFLATION = (1 + BASE_ANNUAL_INFLATION / 100) ** (Decimal(1) / 12) - 1


def make_track(**overrides: object) -> Track:
    fields: dict[str, object] = {
        "principal": Decimal(25000),
        "term_months": 6,
        "rate_kind": "prime",
        "prime_spread": SPREAD,
        "cpi_linked": False,
        "method": "spitzer",
    }
    return Track(**{**fields, **overrides})  # type: ignore[arg-type]


def make_history(
    boi: Sequence[str],
    inflation: Sequence[str] | None = None,
    current: str = "3.25",
    start: date = date(2000, 1, 1),
) -> MarketHistory:
    months = tuple(
        date(start.year + (start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1, 1)
        for i in range(len(boi))
    )
    return MarketHistory(
        months=months,
        boi_rate=tuple(Decimal(v) for v in boi),
        monthly_inflation=tuple(Decimal(v) for v in inflation or ["0"] * len(boi)),
        current_boi_rate=Decimal(current),
        rate_as_of=date(2026, 10, 20),
        cpi_as_of=date(2026, 9, 1),
        consumer_rate=Decimal("7.9"),
        consumer_rate_month=date(2026, 8, 1),
        consumer_month_prime=Decimal("5.0"),
    )


def prime_rates(boi_path: Sequence[Decimal]) -> list[Decimal]:
    return [boi + PRIME_MARGIN + SPREAD for boi in boi_path]


def replay_rates(history: MarketHistory, s: int, n: int) -> list[Decimal]:
    boi = history.boi_rate
    return prime_rates([history.current_boi_rate + boi[s + k] - boi[s] for k in range(n)])


def test_fixed_unlinked_has_no_risk() -> None:
    track = make_track(rate_kind="fixed", annual_rate=Decimal("7.75"), prime_spread=None)
    outcome = simulate(track, make_history(["1", "2", "3", "4", "5", "6", "7"]))
    assert outcome.worst is None
    assert outcome.max_payment_range is None
    assert outcome.total_paid_range is None
    assert outcome.windows == 0
    assert outcome.base == schedule(track, [Decimal("7.75")] * 6, [BASE_MONTHLY_INFLATION] * 6)


def test_prime_base_path_holds_todays_prime() -> None:
    track = make_track()
    outcome = simulate(track, make_history(["1"] * 6))
    expected = schedule(track, prime_rates([Decimal("3.25")] * 6), [Decimal(0)] * 6)
    assert outcome.base.rows == expected.rows


def test_prime_replays_changes_not_levels() -> None:
    rise = [Decimal("0.1") + Decimal("4.65") * i / 14 for i in range(15)]
    history = make_history([str(v) for v in rise] + ["4.75"] * 5)
    track = make_track(term_months=15)
    outcome = simulate(track, history)
    assert outcome.worst is not None
    assert outcome.worst.start == date(2000, 1, 1)
    assert outcome.worst.end == date(2001, 3, 1)
    by_changes = schedule(track, replay_rates(history, 0, 15), [Decimal(0)] * 15)
    assert by_changes.rows[-1].annual_rate == (
        Decimal("3.25") + Decimal("4.65") + PRIME_MARGIN + SPREAD
    )
    assert outcome.worst.max_payment == by_changes.max_payment
    assert outcome.worst.total_paid == by_changes.total_paid
    by_levels = schedule(track, prime_rates(rise), [Decimal(0)] * 15)
    assert outcome.worst.max_payment != by_levels.max_payment


def test_rate_floor() -> None:
    history = make_history(["5", "4", "3", "2", "1", "0"], current="1")
    track = make_track()
    outcome = simulate(track, history)
    floored = prime_rates([Decimal(v) for v in ["1", "0", "0", "0", "0", "0"]])
    expected = schedule(track, floored, [Decimal(0)] * 6)
    assert outcome.worst is not None
    assert outcome.worst.total_paid == expected.total_paid


def test_rate_today_is_the_first_month_rate_of_the_base_path() -> None:
    history = make_history(["1"] * 6)
    assert rate_today(make_track(), history) == Decimal("3.25") + PRIME_MARGIN + SPREAD
    fixed = make_track(rate_kind="fixed", annual_rate=Decimal(4), prime_spread=None)
    assert rate_today(fixed, history) == Decimal(4)
    for track in (make_track(), fixed):
        assert rate_today(track, history) == simulate(track, history).base.rows[0].annual_rate


def test_worst_is_highest_peak_payment() -> None:
    # Window 0 has the highest total (an early, lasting rise); window 2 has the highest payment
    # (a late spike).
    history = make_history(["1", "2", "2", "2", "2", "2", "2", "12"], current="3")
    outcome = simulate(make_track(), history)
    assert outcome.windows == 3
    assert outcome.worst is not None
    assert outcome.max_payment_range is not None and outcome.total_paid_range is not None
    assert outcome.worst.start == date(2000, 3, 1)
    assert outcome.worst.max_payment == outcome.max_payment_range[1]
    assert outcome.worst.total_paid < outcome.total_paid_range[1]


def test_peak_payment_excludes_balloon_clearance() -> None:
    # Window 0 has the higher recurring payment (a rate rise); window 1 has the higher last-month
    # payment (5% inflation indexes the balloon just before it is cleared).
    inflation = ["0", "0", "0", "0", "0", "0", "0.05"]
    history = make_history(["1", "5", "5", "5", "5", "5", "5"], inflation, current="3")
    track = make_track(cpi_linked=True, method="balloon", balloon_amount=Decimal(20000))
    first, second = (
        schedule(track, replay_rates(history, s, 6), [Decimal(v) for v in inflation[s : s + 6]])
        for s in range(2)
    )
    assert first.rows[-1].payment < second.rows[-1].payment
    outcome = simulate(track, history)
    assert outcome.worst is not None
    assert outcome.worst.start == date(2000, 1, 1)
    assert outcome.worst.max_payment == first.max_payment
    assert outcome.worst.balloon_due == first.balloon_due
    assert outcome.max_payment_range == (second.max_payment, first.max_payment)
    assert second.balloon_due is not None and second.balloon_due > 20000


def test_worst_is_earliest_on_tie() -> None:
    outcome = simulate(make_track(), make_history(["2"] * 8))
    assert outcome.windows == 3
    assert outcome.worst is not None
    assert outcome.worst.start == date(2000, 1, 1)


def test_linked_uses_window_inflation() -> None:
    inflation = ["0.001", "0.002", "0", "0.001", "0", "0.003", "0.05"]
    track = make_track(
        rate_kind="fixed", annual_rate=Decimal(5), prime_spread=None, cpi_linked=True
    )
    flat_boi = simulate(track, make_history(["1"] * 7, inflation))
    moving_boi = simulate(track, make_history(["1", "2", "3", "4", "5", "6", "9"], inflation))
    assert flat_boi == moving_boi
    expected = schedule(track, [Decimal(5)] * 6, [Decimal(v) for v in inflation[1:]])
    assert flat_boi.worst is not None
    assert flat_boi.worst.start == date(2000, 2, 1)
    assert flat_boi.worst.max_payment == expected.max_payment
    assert flat_boi.worst.total_paid == expected.total_paid
    assert flat_boi.base == schedule(track, [Decimal(5)] * 6, [BASE_MONTHLY_INFLATION] * 6)


def test_prime_and_linked_move_together() -> None:
    boi = ["1", "1.5", "2", "2.5", "3", "3.5"]
    inflation = ["0.01", "0.002", "0.004", "0", "0.003", "0.006"]
    history = make_history(boi, inflation)
    track = make_track(cpi_linked=True)
    outcome = simulate(track, history)
    expected = schedule(track, replay_rates(history, 0, 6), [Decimal(v) for v in inflation])
    assert outcome.windows == 1
    assert outcome.worst is not None
    assert outcome.worst.max_payment == expected.max_payment
    assert outcome.worst.total_paid == expected.total_paid


def test_ranges_span_all_windows() -> None:
    history = make_history(["2", "2.5", "1.5", "3", "2", "4", "1", "2.25", "3.5"])
    track = make_track()
    outcome = simulate(track, history)
    replays: list[Schedule] = [
        schedule(track, replay_rates(history, s, 6), [Decimal(0)] * 6) for s in range(4)
    ]
    assert outcome.windows == 4
    peaks = [r.max_payment for r in replays]
    totals = [r.total_paid for r in replays]
    assert outcome.max_payment_range == (min(peaks), max(peaks))
    assert outcome.total_paid_range == (min(totals), max(totals))


def test_windows_start_within_the_last_history_months() -> None:
    history = make_history(["9", "9"] + ["2"] * HISTORY_MONTHS)
    outcome = simulate(make_track(), history)
    assert outcome.windows == HISTORY_MONTHS - 6 + 1
    assert outcome.worst is not None
    assert outcome.worst.start == history.months[2]


def test_term_longer_than_history_raises() -> None:
    with pytest.raises(NoHistoryWindowError, match=r"6 months.*5 months.*last 120 months"):
        simulate(make_track(), make_history(["2"] * 5))


def test_history_months_must_be_consecutive() -> None:
    history = make_history(["1", "2", "3"])
    months = (history.months[0], history.months[1], date(2000, 4, 1))
    with pytest.raises(ValueError, match="2000-02 is followed by 2000-04"):
        dataclasses.replace(history, months=months)
