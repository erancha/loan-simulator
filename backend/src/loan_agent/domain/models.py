"""Framework-free types of the loan agent: people, finances, loans, checks, options and
recommendations.

- User, and the VerifiedToken that names them
- Finances (partial until the person has told both figures), LoanRequest
- Check, which holds the loan, the term, the payment ceiling and the finances
- Option with its OptionFigures, Recommendation

Money is Decimal. Datetimes are timezone-aware UTC.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from loan_agent.domain.errors import FinancesError, LoanError

_MONEY_FIELDS = ("net_fixed_income", "fixed_expenses")


def _require_utc(name: str, value: datetime) -> None:
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")


def _money(name: str, value: object) -> Decimal:
    if isinstance(value, (bool, float)):
        raise FinancesError(
            f"{name} must be a Decimal, an integer or a decimal string, not {value!r}"
        )
    if not isinstance(value, Decimal | int | str):
        raise FinancesError(f"{name} must be a Decimal, an integer or a decimal string")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise FinancesError(f"{name} is not a number: {value!r}") from None
    if not amount.is_finite():
        raise FinancesError(f"{name} must be a finite number")
    if amount < 0:
        raise FinancesError(f"{name} cannot be negative")
    return amount


@dataclass(frozen=True)
class User:
    id: str
    email: str | None
    name: str | None


@dataclass(frozen=True)
class VerifiedToken:
    user: User
    expires_at: datetime


@dataclass(frozen=True)
class Finances:
    """The person's monthly finances in ₪; None marks a figure not yet told.

    Fields run from money coming in to money going out, the order missing() lists them, so the
    agent asks in that order too."""

    net_fixed_income: Decimal | None = None
    fixed_expenses: Decimal | None = None

    def missing(self) -> tuple[str, ...]:
        return tuple(name for name in _MONEY_FIELDS if getattr(self, name) is None)

    def merged(self, update: Mapping[str, object]) -> "Finances":
        unknown = sorted(set(update) - set(_MONEY_FIELDS))
        if unknown:
            raise FinancesError(f"Unknown finances field: {', '.join(unknown)}")
        converted = {name: _money(name, value) for name, value in update.items()}
        return replace(self, **converted)

    def engine_profile(self) -> dict[str, str]:
        """The engine's Profile arguments, as decimal strings."""
        missing = self.missing()
        if missing:
            raise FinancesError(f"Finances are incomplete; still missing: {', '.join(missing)}")
        return {name: str(getattr(self, name)) for name in _MONEY_FIELDS}


# The purpose the term card treats as a car loan, stored in this normalised form.
CAR_PURPOSE = "רכב"
# The term the card proposes for a car loan.
CAR_TERM_MONTHS = 60
# The first payment the card aims for when it proposes a term for another purpose.
FIRST_PAYMENT_TARGET = Decimal(1000)


@dataclass(frozen=True)
class LoanRequest:
    """purpose is None until the person names one; amount is in ₪."""

    purpose: str | None
    amount: Decimal

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise LoanError("amount must be greater than zero")


CeilingSource = Literal["stated", "finances"]


@dataclass(frozen=True)
class Check:
    """The loan, its term and the payment ceiling are None until set. The ceiling is either
    stated by the person or derived from their finances, and ceiling_source says which; the two
    are set together. archived_at is set when the person archives the check, which makes it
    read-only; an archived check can always be restored."""

    id: str
    user_id: str
    created_at: datetime
    loan: LoanRequest | None
    term_months: int | None
    payment_ceiling: Decimal | None
    ceiling_source: CeilingSource | None
    finances: Finances
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_utc("created_at", self.created_at)
        if self.archived_at is not None:
            _require_utc("archived_at", self.archived_at)
        assert (self.payment_ceiling is None) == (self.ceiling_source is None), (
            "payment_ceiling and ceiling_source are set together"
        )


# An example illustrates a loan before any lender's offer; nobody can take it, and a check that
# holds a real offer of its loan amount holds no example.
OptionSource = Literal["example", "offer"]


@dataclass(frozen=True)
class OptionFigures:
    first_payment: Decimal
    peak_payment: Decimal
    worst_peak_payment: Decimal | None
    worst_start: date | None
    worst_end: date | None
    balloon_due: Decimal | None
    total_paid: Decimal
    rate_as_of: date
    cpi_as_of: date

    @property
    def risk_payment(self) -> Decimal:
        if self.worst_peak_payment is not None:
            return self.worst_peak_payment
        return self.peak_payment

    def to_json(self) -> dict[str, str | None]:
        """The one encoding of the figures, stored and sent to the page alike: money as decimal
        strings, dates as ISO strings."""
        return {
            "first_payment": str(self.first_payment),
            "peak_payment": str(self.peak_payment),
            "worst_peak_payment": _text_or_none(self.worst_peak_payment),
            "worst_start": _iso_or_none(self.worst_start),
            "worst_end": _iso_or_none(self.worst_end),
            "balloon_due": _text_or_none(self.balloon_due),
            "total_paid": str(self.total_paid),
            "rate_as_of": self.rate_as_of.isoformat(),
            "cpi_as_of": self.cpi_as_of.isoformat(),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "OptionFigures":
        return cls(
            first_payment=Decimal(data["first_payment"]),
            peak_payment=Decimal(data["peak_payment"]),
            worst_peak_payment=_decimal_or_none(data["worst_peak_payment"]),
            worst_start=_date_or_none(data["worst_start"]),
            worst_end=_date_or_none(data["worst_end"]),
            balloon_due=_decimal_or_none(data["balloon_due"]),
            total_paid=Decimal(data["total_paid"]),
            rate_as_of=date.fromisoformat(data["rate_as_of"]),
            cpi_as_of=date.fromisoformat(data["cpi_as_of"]),
        )


def _decimal_or_none(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _text_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _date_or_none(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _iso_or_none(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


@dataclass(frozen=True)
class Option:
    id: str
    check_id: str
    loan: Mapping[str, object]
    source: OptionSource
    lender: str | None
    offer_date: date | None
    max_term_months: int | None
    """For a real offer that leaves its term open, the longest term its lender allows; the offer
    is priced at the check's term up to it."""
    summary: OptionFigures
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc("created_at", self.created_at)


@dataclass(frozen=True)
class Recommendation:
    check_id: str
    preferred_option_id: str
    alternative_option_id: str | None
    reasoning: str
    loan_amount: Decimal
    payment_ceiling: Decimal | None
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc("created_at", self.created_at)

    @property
    def checked(self) -> bool:
        return self.payment_ceiling is not None
