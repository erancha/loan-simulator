"""Replay of one track against every historical window of its term.

- MarketHistory: aligned monthly Bank of Israel rate and CPI series plus the latest market values
- Window: the outcome of one replayed window
- TrackOutcome: the base schedule, the worst window and the range across all windows
- simulate(): prices the track on the base path (DEFAULT_SCENARIO) and replays each window's
  rate changes and inflation
- price(): prices the track on a scenario, with no historical window
- resolved(): a scenario with each movement given as the last years turned into its yearly figure
- rate_today(): the annual rate the track charges in its first month on the base path
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from loan_engine.domain.assumptions import BOI_RATE_FLOOR, HISTORY_MONTHS, PRIME_MARGIN
from loan_engine.domain.models import DEFAULT_SCENARIO, Scenario, Track
from loan_engine.domain.schedule import Schedule, schedule

_HUNDREDTH = Decimal("0.01")


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
    """Price the track on the base path and on every window starting in the last HISTORY_MONTHS.

    Worst is the window with the highest peak recurring payment, the earliest one on a tie; the
    balloon each window clears in its last month is reported beside it, not counted in the peak.
    """
    n = track.term_months
    base = price(track, history, DEFAULT_SCENARIO)
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


def price(track: Track, history: MarketHistory, scenario: Scenario) -> Schedule:
    """The CPI rises by cpi_per_year compounded monthly; the Bank of Israel rate, and prime with
    it, by a twelfth of prime_per_year more each month from today's, floored as in a window."""
    n = track.term_months
    inflation = (1 + scenario.cpi_per_year / 100) ** (Decimal(1) / 12) - 1
    deltas = [scenario.prime_per_year * k / 12 for k in range(n)]
    return schedule(track, _rates(track, history, deltas), [inflation] * n)


def resolved(scenario: Scenario, history: MarketHistory) -> Scenario:
    """The CPI's yearly rise over the last years is its compounded rise over those months, to the
    hundredth of a percent; prime's is its change over them divided by the years, to the
    hundredth of a point. Both come from the history's latest months."""
    figures: dict[str, Decimal] = {}
    if scenario.cpi_like_last_years is not None:
        years = scenario.cpi_like_last_years
        months = _last_months(history.monthly_inflation, 12 * years, years)
        rise = Decimal(1)
        for change in months:
            rise *= 1 + change
        figures["cpi_per_year"] = ((rise ** (Decimal(1) / years) - 1) * 100).quantize(_HUNDREDTH)
    if scenario.prime_like_last_years is not None:
        years = scenario.prime_like_last_years
        rates = _last_months(history.boi_rate, 12 * years + 1, years)
        figures["prime_per_year"] = ((rates[-1] - rates[0]) / years).quantize(_HUNDREDTH)
    return scenario.model_copy(update=figures)


def _last_months(series: Sequence[Decimal], count: int, years: int) -> Sequence[Decimal]:
    if len(series) < count:
        raise NoHistoryWindowError(
            f"the last {years} years need {count} months of history; it holds {len(series)}"
        )
    return series[-count:]


def rate_today(track: Track, history: MarketHistory) -> Decimal:
    """The fixed rate, or today's prime plus the spread; for a CPI-linked track, the rate on top
    of the CPI."""
    (rate,) = _rates(track, history, [Decimal(0)])
    return rate


def _month_index(month: date) -> int:
    return month.year * 12 + month.month


def _window_starts(n: int, history: MarketHistory) -> range:
    first = max(len(history.months) - HISTORY_MONTHS, 0)
    available = len(history.months) - first
    if available < n:
        raise NoHistoryWindowError(
            f"term of {n} months exceeds the {available} months of history available "
            f"in the last {HISTORY_MONTHS} months"
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
