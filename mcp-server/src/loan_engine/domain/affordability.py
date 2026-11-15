"""The household payment ceiling, the only calculation that reads the borrower's finances.

- Bounds: the highest monthly loan payment, the income it rests on and the reasons it was set
- assess_affordability(): the ceiling, the lower of a share of income and a share of what remains
  after fixed expenses, never below zero
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from loan_engine.domain.assumptions import DISPOSABLE_SHARE_CAP, INCOME_SHARE_CAP
from loan_engine.domain.models import Profile

Reason = Literal[
    "ceiling_by_income_share",
    "ceiling_by_disposable_income",
    "no_room_for_payment",
]


@dataclass(frozen=True)
class Bounds:
    payment_ceiling: Decimal
    counted_income: Decimal
    reasons: list[Reason]


def assess_affordability(profile: Profile) -> Bounds:
    income = profile.net_fixed_income
    by_share = INCOME_SHARE_CAP * income
    by_disposable = DISPOSABLE_SHARE_CAP * (income - profile.fixed_expenses)
    reasons: list[Reason] = [
        "ceiling_by_income_share" if by_share <= by_disposable else "ceiling_by_disposable_income"
    ]
    ceiling = max(min(by_share, by_disposable), Decimal(0))
    if ceiling == 0:
        reasons.append("no_room_for_payment")
    return Bounds(ceiling, income, reasons)
