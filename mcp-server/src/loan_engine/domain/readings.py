"""The one-track loans a lender's offer may mean when its words leave the loan's type open.

- Reading: one candidate loan, its first payment and the annual rate it charges today
- OfferReadings: the readings of one offer, today's prime and the rate its payment implies
- rate_for_payment(): the fixed unlinked rate whose first spitzer payment is the quoted payment
- offer_readings(): the readings from a stated number, or from the payment when none is stated
- NoOfferFigureError: an offer that states neither a number nor a payment
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from loan_engine.domain.assumptions import PRIME_MARGIN
from loan_engine.domain.history import MarketHistory, simulate
from loan_engine.domain.limits import (
    MAX_ANNUAL_RATE,
    MAX_PRIME_SPREAD,
    MIN_ANNUAL_RATE,
    MIN_PRIME_SPREAD,
)
from loan_engine.domain.models import Track
from loan_engine.domain.schedule import schedule

ReadingKind = Literal["prime_margin", "prime_total", "fixed_unlinked", "fixed_linked"]

RATE_STEP = Decimal("0.01")

_PRIME_KINDS: frozenset[ReadingKind] = frozenset({"prime_margin", "prime_total"})

# Each bisection halves the rate bracket, which starts as the whole priced range; 40 leave it
# far below RATE_STEP.
_BISECTIONS = 40


class NoOfferFigureError(ValueError):
    pass


@dataclass(frozen=True)
class Reading:
    """approximate marks a linked reading priced from the rate of an unlinked payment, since a
    linked loan's first payment already carries a month of indexation."""

    kind: ReadingKind
    track: Track
    first_payment: Decimal
    total_rate: Decimal
    approximate: bool


@dataclass(frozen=True)
class OfferReadings:
    """payment_rate is None when no payment was quoted or no rate in the priced range gives it."""

    prime: Decimal
    payment_rate: Decimal | None
    readings: tuple[Reading, ...]


def rate_for_payment(principal: Decimal, term_months: int, payment: Decimal) -> Decimal | None:
    """The annual percent, to RATE_STEP, at which a fixed unlinked spitzer track starts with the
    payment; None when the payment is below the payment at MIN_ANNUAL_RATE or above the one at
    MAX_ANNUAL_RATE."""

    def first_payment(rate: Decimal) -> Decimal:
        track = _track(principal, term_months, "fixed", rate, False)
        return schedule(track, [rate] * term_months, []).first_payment

    low, high = Decimal(MIN_ANNUAL_RATE), Decimal(MAX_ANNUAL_RATE)
    if not first_payment(low) <= payment <= first_payment(high):
        return None
    for _ in range(_BISECTIONS):
        middle = (low + high) / 2
        if first_payment(middle) < payment:
            low = middle
        else:
            high = middle
    return high.quantize(RATE_STEP, rounding=ROUND_HALF_UP)


def offer_readings(
    principal: Decimal,
    term_months: int,
    stated_rate: Decimal | None,
    monthly_payment: Decimal | None,
    prime_total: bool,
    history: MarketHistory,
) -> OfferReadings:
    """The readings of a stated number X, in the order of ReadingKind, prime_total only when
    asked; with no number, the readings of the rate r its payment implies: fixed r, prime at the
    total r, and fixed r linked. A reading whose rate or spread is outside the priced ranges is
    left out."""
    if stated_rate is None and monthly_payment is None:
        raise NoOfferFigureError("an offer needs stated_rate or monthly_payment, got neither")
    prime = history.current_boi_rate + PRIME_MARGIN
    payment_rate = (
        None
        if monthly_payment is None
        else rate_for_payment(principal, term_months, monthly_payment)
    )
    # Each candidate's rate is its track's own: the spread over prime for a prime kind, the
    # annual rate for a fixed one.
    if stated_rate is not None:
        candidates: list[tuple[ReadingKind, Decimal, bool]] = [
            ("prime_margin", stated_rate, False),
            ("fixed_unlinked", stated_rate, False),
            ("fixed_linked", stated_rate, False),
        ]
        if prime_total:
            candidates.insert(1, ("prime_total", stated_rate - prime, False))
    elif payment_rate is not None:
        candidates = [
            ("fixed_unlinked", payment_rate, False),
            ("prime_margin", payment_rate - prime, False),
            ("fixed_linked", payment_rate, True),
        ]
    else:
        candidates = []
    readings = tuple(
        _reading(kind, principal, term_months, rate, prime, approximate, history)
        for kind, rate, approximate in candidates
        if _priced(kind, rate)
    )
    return OfferReadings(prime, payment_rate, readings)


def _priced(kind: ReadingKind, rate: Decimal) -> bool:
    if kind in _PRIME_KINDS:
        return MIN_PRIME_SPREAD <= rate <= MAX_PRIME_SPREAD
    return MIN_ANNUAL_RATE <= rate <= MAX_ANNUAL_RATE


def _reading(
    kind: ReadingKind,
    principal: Decimal,
    term_months: int,
    rate: Decimal,
    prime: Decimal,
    approximate: bool,
    history: MarketHistory,
) -> Reading:
    if kind in _PRIME_KINDS:
        track = _track(principal, term_months, "prime", rate, False)
        total_rate = prime + rate
    else:
        track = _track(principal, term_months, "fixed", rate, kind == "fixed_linked")
        total_rate = rate
    first_payment = simulate(track, history).base.first_payment
    return Reading(kind, track, first_payment, total_rate, approximate)


def _track(
    principal: Decimal,
    term_months: int,
    rate_kind: Literal["fixed", "prime"],
    rate: Decimal,
    cpi_linked: bool,
) -> Track:
    return Track(
        principal=principal,
        term_months=term_months,
        rate_kind=rate_kind,
        annual_rate=rate if rate_kind == "fixed" else None,
        prime_spread=rate if rate_kind == "prime" else None,
        cpi_linked=cpi_linked,
        method="spitzer",
    )
