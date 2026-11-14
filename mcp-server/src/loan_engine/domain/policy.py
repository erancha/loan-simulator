"""Affordability bounds from the borrower's profile, loan sizing and typical tracks.

- assess_affordability(): payment ceiling and savings cushion from the borrower's profile
- size_loan(): the amount to borrow after spendable savings
- suggest_tracks(): fixed and prime tracks priced from the published average bank rate
- shortest_comfortable_term(): the shortest term at which those tracks fit the payment ceiling
- shortest_comfortable_offer_term(): the same search for one real offer, up to its longest term
- largest_comfortable_loan(): the largest loan whose tracks fit the ceiling at the longest term
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from loan_engine.domain.assumptions import (
    COMFORT_SHARE,
    CUSHION_MONTHS,
    DISPOSABLE_SHARE_CAP,
    INCOME_SHARE_CAP,
    LOAN_STEP,
    TERM_STEP,
)
from loan_engine.domain.history import MarketHistory, simulate
from loan_engine.domain.limits import MAX_PRINCIPAL, MAX_TERM, MIN_PRINCIPAL
from loan_engine.domain.models import Profile, Track

Reason = Literal[
    "variable_income_minimum_counted",
    "ceiling_by_income_share",
    "ceiling_by_disposable_income",
    "existing_loans_deducted",
    "no_room_for_payment",
]


@dataclass(frozen=True)
class Bounds:
    payment_ceiling: Decimal
    min_cushion: Decimal
    counted_income: Decimal
    reasons: list[Reason]


@dataclass(frozen=True)
class Sizing:
    """loan_amount may be 0 or below MIN_PRINCIPAL; the caller decides what to do with it."""

    loan_amount: Decimal
    savings_used: Decimal
    cushion_kept: Decimal
    spare_savings: Decimal


def assess_affordability(profile: Profile) -> Bounds:
    reasons: list[Reason] = []
    counted = profile.net_fixed_income + profile.variable_income_minimum
    if profile.variable_income_minimum > 0:
        reasons.append("variable_income_minimum_counted")

    by_share = INCOME_SHARE_CAP * counted
    by_disposable = DISPOSABLE_SHARE_CAP * (counted - profile.fixed_expenses)
    reasons.append(
        "ceiling_by_income_share" if by_share <= by_disposable else "ceiling_by_disposable_income"
    )

    if profile.existing_loan_payments > 0:
        reasons.append("existing_loans_deducted")
    ceiling = max(min(by_share, by_disposable) - profile.existing_loan_payments, Decimal(0))
    if ceiling == 0:
        reasons.append("no_room_for_payment")

    return Bounds(ceiling, CUSHION_MONTHS * profile.fixed_expenses, counted, reasons)


def size_loan(goal_price: Decimal, savings: Decimal, min_cushion: Decimal) -> Sizing:
    need = goal_price
    available = max(savings - min_cushion, Decimal(0))
    savings_used = min(available, need)
    return Sizing(
        loan_amount=need - savings_used,
        savings_used=savings_used,
        cushion_kept=savings - available,
        spare_savings=available - savings_used,
    )


def suggest_tracks(principal: Decimal, term_months: int, history: MarketHistory) -> list[Track]:
    """Unlinked tracks only: no published series covers CPI-linked consumer loans."""
    common = {
        "principal": principal,
        "term_months": term_months,
        "cpi_linked": False,
        "method": "spitzer",
    }
    return [
        Track(rate_kind="fixed", annual_rate=history.consumer_rate, **common),  # type: ignore[arg-type]
        Track(
            rate_kind="prime",
            prime_spread=history.consumer_rate - history.consumer_month_prime,
            **common,  # type: ignore[arg-type]
        ),
    ]


def shortest_comfortable_term(
    principal: Decimal, payment_ceiling: Decimal, history: MarketHistory
) -> int | None:
    """The shortest term, in TERM_STEP-month steps up to MAX_TERM, at which every suggested
    track's highest recurring payment, in its worst historical window for a variable track, stays
    within COMFORT_SHARE of the payment ceiling; None when no term does."""
    return _first_comfortable_term(
        range(TERM_STEP, MAX_TERM + 1, TERM_STEP),
        lambda term: suggest_tracks(principal, term, history),
        payment_ceiling,
        history,
    )


def shortest_comfortable_offer_term(
    offer: Track, payment_ceiling: Decimal, history: MarketHistory
) -> int | None:
    """The same search for a real offer whose term_months is the longest it allows: TERM_STEP-month
    steps below that term, then that term itself; None when no term fits."""
    return _first_comfortable_term(
        [*range(TERM_STEP, offer.term_months, TERM_STEP), offer.term_months],
        lambda term: [offer.model_copy(update={"term_months": term})],
        payment_ceiling,
        history,
    )


def largest_comfortable_loan(payment_ceiling: Decimal, history: MarketHistory) -> Decimal | None:
    """The largest loan, in whole LOAN_STEP shekels up to MAX_PRINCIPAL, whose suggested tracks at
    MAX_TERM stay within COMFORT_SHARE of the payment ceiling; None when even MIN_PRINCIPAL does
    not."""

    def peak(principal: Decimal) -> Decimal:
        return _peak_payment(suggest_tracks(principal, MAX_TERM, history), history)

    limit = payment_ceiling * COMFORT_SHARE
    # A suggested track carries no fee, so its payment grows in proportion to the principal and
    # the peak at MIN_PRINCIPAL places the answer; the loop absorbs the rounding of payments.
    proportional = MIN_PRINCIPAL * limit / peak(Decimal(MIN_PRINCIPAL))
    loan = min(proportional // LOAN_STEP * LOAN_STEP, Decimal(MAX_PRINCIPAL))
    while loan >= MIN_PRINCIPAL and peak(loan) > limit:
        loan -= LOAN_STEP
    return loan if loan >= MIN_PRINCIPAL else None


def _peak_payment(tracks: list[Track], history: MarketHistory) -> Decimal:
    """The highest recurring payment among the tracks, in its worst historical window for a
    variable track."""
    outcomes = [simulate(track, history) for track in tracks]
    return max(o.base.max_payment if o.worst is None else o.worst.max_payment for o in outcomes)


def _first_comfortable_term(
    terms: Iterable[int],
    tracks_at: Callable[[int], list[Track]],
    payment_ceiling: Decimal,
    history: MarketHistory,
) -> int | None:
    limit = payment_ceiling * COMFORT_SHARE
    for term in terms:
        if _peak_payment(tracks_at(term), history) <= limit:
            return term
    return None
