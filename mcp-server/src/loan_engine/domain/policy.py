"""Affordability bounds from the borrower's profile, loan sizing and typical tracks.

- assess_affordability(): payment ceiling and savings cushion from the borrower's profile
- size_loan(): the amount to borrow after trade-in and spendable savings
- suggest_tracks(): fixed and prime tracks priced from the published average bank rate
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from loan_engine.domain.assumptions import (
    CUSHION_MONTHS,
    DISPOSABLE_SHARE_CAP,
    INCOME_SHARE_CAP,
    STABLE_VARIABLE_SHARE,
)
from loan_engine.domain.history import MarketHistory
from loan_engine.domain.models import Profile, Track

Reason = Literal[
    "variable_income_excluded",
    "variable_income_half_counted",
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
    counted = profile.net_fixed_income
    if profile.variable_income > 0:
        if profile.variable_income_stable:
            counted += STABLE_VARIABLE_SHARE * profile.variable_income
            reasons.append("variable_income_half_counted")
        else:
            reasons.append("variable_income_excluded")

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


def size_loan(
    goal_price: Decimal, trade_in_value: Decimal, savings: Decimal, min_cushion: Decimal
) -> Sizing:
    need = max(goal_price - trade_in_value, Decimal(0))
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
