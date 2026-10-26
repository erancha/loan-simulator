"""Month-by-month repayment schedule of one track under a given path of rates and inflation.

- MonthRow: one month's payment split into interest and principal, with the closing balance
- Schedule: the rows of a track plus first payment, peak recurring payment, balloon due and total
  paid
- schedule(): the calculation; takes the per-month rates explicitly and never rounds
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from loan_engine.domain.models import Track

_MONTHS_PER_YEAR_PERCENT = Decimal(1200)


@dataclass(frozen=True)
class MonthRow:
    month: int
    annual_rate: Decimal
    payment: Decimal
    interest: Decimal
    principal: Decimal
    balance: Decimal


@dataclass(frozen=True)
class Schedule:
    """Rows of one track and the one-time fee paid on top of the monthly payments.

    balloon_due is the part of the last row's payment that clears the balloon (indexed, for a
    linked track) beyond that month's recurring payment; None when the track has no balloon.
    """

    rows: tuple[MonthRow, ...]
    one_time_fee: Decimal
    balloon_due: Decimal | None

    @property
    def first_payment(self) -> Decimal:
        return self.rows[0].payment

    @property
    def recurring_payments(self) -> tuple[Decimal, ...]:
        """Each month's payment, the last one without the balloon."""
        payments = tuple(row.payment for row in self.rows)
        if self.balloon_due is None:
            return payments
        return (*payments[:-1], payments[-1] - self.balloon_due)

    @property
    def max_payment(self) -> Decimal:
        return max(self.recurring_payments)

    @property
    def total_paid(self) -> Decimal:
        return sum((row.payment for row in self.rows), Decimal(0)) + self.one_time_fee


def schedule(
    track: Track, annual_rates: Sequence[Decimal], monthly_inflation: Sequence[Decimal]
) -> Schedule:
    """Amortize the track with one nominal annual rate (percent) per month.

    The payment is recomputed every month from the remaining balance, remaining months and that
    month's rate. For a linked track the balance and the balloon are first indexed by that
    month's inflation fraction. The last month also clears whatever remains (the balloon and
    rounding residue), so the final balance is exactly 0; for a balloon track that clearance is
    the balloon due.
    """
    n = track.term_months
    if len(annual_rates) != n:
        raise ValueError(f"annual_rates has {len(annual_rates)} items, term_months is {n}")
    if track.cpi_linked and len(monthly_inflation) != n:
        raise ValueError(
            f"monthly_inflation has {len(monthly_inflation)} items, term_months is {n}"
        )

    balance = track.principal
    balloon = track.balloon_amount
    rows: list[MonthRow] = []
    cleared = Decimal(0)
    for month in range(1, n + 1):
        if track.cpi_linked:
            index = 1 + monthly_inflation[month - 1]
            balance *= index
            balloon *= index
        remaining = n - month + 1
        r = annual_rates[month - 1] / _MONTHS_PER_YEAR_PERCENT
        interest = balance * r
        if track.method == "equal_principal":
            payment = balance / remaining + interest
        elif r == 0:
            payment = (balance - balloon) / remaining
        else:
            growth = (1 + r) ** remaining
            payment = (balance - balloon / growth) * r / (1 - 1 / growth)
        principal = payment - interest
        balance -= principal
        if month == n:
            cleared = balance
            payment += balance
            principal += balance
            balance = Decimal(0)
        rows.append(
            MonthRow(
                month,
                annual_rates[month - 1],
                payment + track.monthly_fee,
                interest,
                principal,
                balance,
            )
        )
    balloon_due = cleared if track.method == "balloon" else None
    return Schedule(tuple(rows), track.one_time_fee, balloon_due)
