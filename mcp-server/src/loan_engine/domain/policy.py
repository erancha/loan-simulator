"""Typical tracks and the terms and loan sizes at which they fit a payment ceiling.

- lender_tracks(): fixed and prime tracks, both unlinked, priced from the published average bank
  rate: what most consumer lenders offer
- suggest_tracks(): those two and a pension fund's fixed track linked to the CPI
- shortest_comfortable_term(): the shortest term at which the lender tracks fit the ceiling
- shortest_comfortable_offer_term(): the same search for one real offer, up to its longest term
- proposed_term(), proposed_offer_term(): the shortest term whose first payment is under a limit
- largest_comfortable_loan(): the largest loan on which a track fits the ceiling at a given term
- rate_against_market(): whether an unlinked track's rate today is above, similar to or below
  the published average rate on consumer loans
"""

from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Literal

from loan_engine.domain.assumptions import (
    LOAN_STEP,
    PENSION_FUND_RATE,
    SIMILAR_RATE_POINTS,
    TERM_STEP,
)
from loan_engine.domain.history import MarketHistory, rate_today, simulate
from loan_engine.domain.limits import MAX_PRINCIPAL, MAX_TERM, MIN_PRINCIPAL
from loan_engine.domain.models import Track

_TERMS = range(TERM_STEP, MAX_TERM + 1, TERM_STEP)

RateAgainstMarket = Literal["above", "similar", "below"]


def lender_tracks(principal: Decimal, term_months: int, history: MarketHistory) -> list[Track]:
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


def suggest_tracks(principal: Decimal, term_months: int, history: MarketHistory) -> list[Track]:
    """The lender tracks, then a pension fund's loan to its member: fixed, linked to the CPI."""
    pension = Track(
        principal=principal,
        term_months=term_months,
        rate_kind="fixed",
        annual_rate=PENSION_FUND_RATE,
        cpi_linked=True,
        method="spitzer",
    )
    return [*lender_tracks(principal, term_months, history), pension]


def rate_against_market(track: Track, history: MarketHistory) -> RateAgainstMarket | None:
    """None for a CPI-linked track: its rate is on top of the CPI, so setting it against the
    unlinked average would compare unlike rates."""
    if track.cpi_linked:
        return None
    gap = rate_today(track, history) - history.consumer_rate
    if abs(gap) <= SIMILAR_RATE_POINTS:
        return "similar"
    return "above" if gap > 0 else "below"


def shortest_comfortable_term(
    principal: Decimal,
    payment_ceiling: Decimal,
    history: MarketHistory,
    *,
    any_track: bool = False,
) -> int | None:
    """The shortest term, in TERM_STEP-month steps up to MAX_TERM, at which every lender
    track's highest recurring payment, in its worst historical window for a variable track, stays
    within the payment ceiling, or with any_track at least one track's does; None when no term
    does."""
    return _first_term(
        _TERMS,
        lambda term: lender_tracks(principal, term, history),
        _within_ceiling(payment_ceiling, history, any_track=any_track),
    )


def shortest_comfortable_offer_term(
    offer: Track, payment_ceiling: Decimal, history: MarketHistory
) -> int | None:
    """The same search for a real offer whose term_months is the longest it allows: TERM_STEP-month
    steps below that term, then that term itself; None when no term fits."""
    return _first_term(
        _offer_terms(offer),
        _offer_at(offer),
        _within_ceiling(payment_ceiling, history, any_track=False),
    )


def proposed_term(principal: Decimal, payment_limit: Decimal, history: MarketHistory) -> int:
    """The shortest term, in TERM_STEP-month steps up to MAX_TERM, at which every lender
    track's first payment is below the limit; MAX_TERM when none is."""
    term = _first_term(
        _TERMS,
        lambda term: lender_tracks(principal, term, history),
        _first_payments_below(payment_limit, history),
    )
    return MAX_TERM if term is None else term


def proposed_offer_term(offer: Track, payment_limit: Decimal, history: MarketHistory) -> int:
    """The same over the terms shortest_comfortable_offer_term tries; the offer's own term_months
    when none has a first payment below the limit."""
    term = _first_term(
        _offer_terms(offer), _offer_at(offer), _first_payments_below(payment_limit, history)
    )
    return offer.term_months if term is None else term


def largest_comfortable_loan(
    payment_ceiling: Decimal, term_months: int, history: MarketHistory
) -> Decimal | None:
    """The largest loan, in whole LOAN_STEP shekels up to MAX_PRINCIPAL, for which at least one
    lender track over term_months stays within the payment ceiling; None when even
    MIN_PRINCIPAL does not."""

    def best_peak(principal: Decimal) -> Decimal:
        return min(_peak_payments(lender_tracks(principal, term_months, history), history))

    # A lender track carries no fee, so its payment grows in proportion to the principal and
    # the peak at MIN_PRINCIPAL places the answer; the loop absorbs the rounding of payments.
    proportional = MIN_PRINCIPAL * payment_ceiling / best_peak(Decimal(MIN_PRINCIPAL))
    loan = min(proportional // LOAN_STEP * LOAN_STEP, Decimal(MAX_PRINCIPAL))
    while loan >= MIN_PRINCIPAL and best_peak(loan) > payment_ceiling:
        loan -= LOAN_STEP
    return loan if loan >= MIN_PRINCIPAL else None


def _peak_payments(tracks: list[Track], history: MarketHistory) -> list[Decimal]:
    """Each track's highest recurring payment, in its worst historical window for a variable
    track."""
    outcomes = [simulate(track, history) for track in tracks]
    return [o.base.max_payment if o.worst is None else o.worst.max_payment for o in outcomes]


def _offer_terms(offer: Track) -> list[int]:
    return [*range(TERM_STEP, offer.term_months, TERM_STEP), offer.term_months]


def _offer_at(offer: Track) -> Callable[[int], list[Track]]:
    return lambda term: [offer.model_copy(update={"term_months": term})]


def _within_ceiling(
    payment_ceiling: Decimal, history: MarketHistory, *, any_track: bool
) -> Callable[[list[Track]], bool]:
    fits = min if any_track else max
    return lambda tracks: fits(_peak_payments(tracks, history)) <= payment_ceiling


def _first_payments_below(
    payment_limit: Decimal, history: MarketHistory
) -> Callable[[list[Track]], bool]:
    return lambda tracks: all(
        simulate(track, history).base.first_payment < payment_limit for track in tracks
    )


def _first_term(
    terms: Iterable[int],
    tracks_at: Callable[[int], list[Track]],
    accepts: Callable[[list[Track]], bool],
) -> int | None:
    """The first of the terms at which the tracks it gives are accepted; None when none is."""
    return next((term for term in terms if accepts(tracks_at(term))), None)
