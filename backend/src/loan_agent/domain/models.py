"""Framework-free types of the loan agent: people, finances, goals, checks, options and
recommendations.

- User, and the VerifiedToken that names them
- Profile (partial until the person has told everything), Goal
- Check, Option with its OptionFigures, Recommendation

Money is Decimal. Datetimes are timezone-aware UTC.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from loan_agent.domain.errors import GoalError, ProfileError

_MONEY_FIELDS = (
    "net_fixed_income",
    "variable_income",
    "fixed_expenses",
    "existing_loan_payments",
    "savings",
)
_ENGINE_FIELDS = (
    "net_fixed_income",
    "variable_income",
    "variable_income_stable",
    "fixed_expenses",
    "existing_loan_payments",
)


def _require_utc(name: str, value: datetime) -> None:
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")


def _money(name: str, value: object) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ProfileError(
            f"{name} must be a Decimal, an integer or a decimal string, not {value!r}"
        )
    if not isinstance(value, Decimal | int | str):
        raise ProfileError(f"{name} must be a Decimal, an integer or a decimal string")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ProfileError(f"{name} is not a number: {value!r}") from None
    if not amount.is_finite():
        raise ProfileError(f"{name} must be a finite number")
    if amount < 0:
        raise ProfileError(f"{name} cannot be negative")
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
class Profile:
    """The person's monthly finances in ₪ and their savings; None marks a field not yet told."""

    net_fixed_income: Decimal | None = None
    variable_income: Decimal | None = None
    variable_income_stable: bool | None = None
    fixed_expenses: Decimal | None = None
    existing_loan_payments: Decimal | None = None
    savings: Decimal | None = None

    def missing(self) -> tuple[str, ...]:
        return tuple(f.name for f in fields(self) if getattr(self, f.name) is None)

    def merged(self, update: Mapping[str, object]) -> "Profile":
        known = {f.name for f in fields(self)}
        unknown = sorted(set(update) - known)
        if unknown:
            raise ProfileError(f"Unknown profile field: {', '.join(unknown)}")
        converted: dict[str, Any] = {}
        for name, value in update.items():
            if name == "variable_income_stable":
                if not isinstance(value, bool):
                    raise ProfileError("variable_income_stable must be true or false")
                converted[name] = value
            else:
                converted[name] = _money(name, value)
        return replace(self, **converted)

    def engine_profile(self) -> dict[str, str | bool]:
        """The engine's Profile arguments; savings stay agent-side (they go to size_loan)."""
        missing = [name for name in self.missing() if name in _ENGINE_FIELDS]
        if missing:
            raise ProfileError(f"Profile is incomplete; still missing: {', '.join(missing)}")
        result: dict[str, str | bool] = {}
        for name in _ENGINE_FIELDS:
            value = getattr(self, name)
            result[name] = value if isinstance(value, bool) else str(value)
        return result


@dataclass(frozen=True)
class Goal:
    purpose: str
    price: Decimal
    trade_in_value: Decimal

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise GoalError("price must be greater than zero")
        if self.trade_in_value < 0:
            raise GoalError("trade_in_value cannot be negative")


@dataclass(frozen=True)
class Check:
    id: str
    user_id: str
    created_at: datetime
    goal: Goal | None
    profile_snapshot_at: datetime | None

    def __post_init__(self) -> None:
        _require_utc("created_at", self.created_at)
        if self.profile_snapshot_at is not None:
            _require_utc("profile_snapshot_at", self.profile_snapshot_at)

    def is_stale(self, profile_updated_at: datetime | None) -> bool:
        """Whether the profile was saved after the version the recommendation was computed from.
        profile_updated_at: when the person's profile was last saved; None when they have none."""
        if self.profile_snapshot_at is None:
            return False
        assert profile_updated_at is not None, "a snapshot records a profile save"
        return profile_updated_at > self.profile_snapshot_at


OptionSource = Literal["published_average", "offer"]


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
    payment_ceiling: Decimal
    min_cushion: Decimal
    cushion_kept: Decimal
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc("created_at", self.created_at)
