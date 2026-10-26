"""Replay of one track against every historical window of its term.

- MarketHistory: aligned monthly Bank of Israel rate and CPI series plus the latest market values
- Window: the outcome of one replayed window
- TrackOutcome: the base schedule, the worst window and the range across all windows
- simulate(): prices the track on the base path (today's rate held flat, BASE_ANNUAL_INFLATION
  each month) and replays each window's rate changes and inflation
"""

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from loan_engine.domain.assumptions import (
    BASE_ANNUAL_INFLATION,
    BOI_RATE_FLOOR,
    HISTORY_START,
    PRIME_MARGIN,
)
from loan_engine.domain.models import Track
from loan_engine.domain.schedule import Schedule, schedule

_BASE_MONTHLY_INFLATION = (1 + BASE_ANNUAL_INFLATION / 100) ** (Decimal(1) / 12) - 1


class NoHistoryWindowError(ValueError):
    pass


@dataclass(frozen=True)
class MarketHistory:
    """Monthly series keyed by consecutive first-of-month dates, and the latest market values.

    boi_rate is the Bank of Israel rate (percent) in effect on each date; monthly_inflation is
    that month's CPI change as a fraction. consumer_rate is the latest published average rate
    on new household consumer loans, for consumer_rate_month, and consumer_month_prime the prime
    in effect on the first of that month.
    """

    months: tuple[date, ...]
    boi_rate: tuple[Decimal, ...]
    monthly_inflation: tuple[Decimal, ...]
    current_boi_rate: Decimal
    rate_as_of: date
    cpi_as_of: date
    consumer_rate: Decimal
    consumer_rate_month: date
    consumer_month_prime: Decimal

    def __post_init__(self) -> None:
        if not len(self.months) == len(self.boi_rate) == len(self.monthly_inflation):
            raise ValueError(
                f"series are not aligned: {len(self.months)} months, "
                f"{len(self.boi_rate)} rates, {len(self.monthly_inflation)} inflation values"
            )
        for previous, month in pairwise(self.months):
            if _month_index(month) - _month_index(previous) != 1:
                raise ValueError(
                    f"months are not consecutive: {previous:%Y-%m} is followed by {month:%Y-%m}"
                )


@dataclass(frozen=True)
class Window:
    """One replayed window; max_payment is its peak recurring payment, without the balloon."""

    start: date
    end: date
    max_payment: Decimal
    balloon_due: Decimal | None
    total_paid: Decimal


@dataclass(frozen=True)
class TrackOutcome:
    """Base schedule and replay results; worst and the ranges are None for a fixed unlinked track,
    whose payments no market path changes."""

    base: Schedule
    worst: Window | None
    max_payment_range: tuple[Decimal, Decimal] | None
    total_paid_range: tuple[Decimal, Decimal] | None
    windows: int


def simulate(track: Track, history: MarketHistory) -> TrackOutcome:
    """Price the track on the base path and on every window from HISTORY_START.

    Worst is the window with the highest peak recurring payment, the earliest one on a tie; the
    balloon each window clears in its last month is reported beside it, not counted in the peak.
    """
    n = track.term_months
    base = schedule(track, _rates(track, history, [Decimal(0)] * n), [_BASE_MONTHLY_INFLATION] * n)
    if track.rate_kind == "fixed" and not track.cpi_linked:
        return TrackOutcome(base, None, None, None, 0)

    windows = [_replay(track, history, s) for s in _window_starts(n, history)]
    peaks = [w.max_payment for w in windows]
    totals = [w.total_paid for w in windows]
    return TrackOutcome(
        base=base,
        worst=max(windows, key=lambda w: w.max_payment),
        max_payment_range=(min(peaks), max(peaks)),
        total_paid_range=(min(totals), max(totals)),
        windows=len(windows),
    )


def _month_index(month: date) -> int:
    return month.year * 12 + month.month


def _window_starts(n: int, history: MarketHistory) -> range:
    first = bisect_left(history.months, HISTORY_START)
    available = len(history.months) - first
    if available < n:
        raise NoHistoryWindowError(
            f"term of {n} months exceeds the {available} months of history available "
            f"from {HISTORY_START:%Y-%m}"
        )
    return range(first, len(history.months) - n + 1)


def _replay(track: Track, history: MarketHistory, s: int) -> Window:
    n = track.term_months
    boi = history.boi_rate
    deltas = [boi[s + k] - boi[s] for k in range(n)]
    result = schedule(track, _rates(track, history, deltas), history.monthly_inflation[s : s + n])
    return Window(
        history.months[s],
        history.months[s + n - 1],
        result.max_payment,
        result.balloon_due,
        result.total_paid,
    )


def _rates(track: Track, history: MarketHistory, boi_deltas: Sequence[Decimal]) -> list[Decimal]:
    """Annual rate per month: a fixed rate as is; for a prime track, the current Bank of Israel
    rate moved by each delta and floored at BOI_RATE_FLOOR, plus PRIME_MARGIN and the spread."""
    if track.rate_kind == "fixed":
        assert track.annual_rate is not None
        return [track.annual_rate] * len(boi_deltas)
    assert track.prime_spread is not None
    spread = track.prime_spread
    return [
        max(history.current_boi_rate + delta, BOI_RATE_FLOOR) + PRIME_MARGIN + spread
        for delta in boi_deltas
    ]
