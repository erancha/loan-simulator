"""Framework-free types of the loan agent: people, finances, loans, checks, options, offers that
await their lender's answer, and recommendations.

- User, and the VerifiedToken that names them
- Finances (partial until the person has told both figures), LoanRequest
- Check, which holds the loan, the term, the payment ceiling and the finances
- Option with its OptionFigures and their OptionPrice, Recommendation, and compares_options:
  whether a recommendation's card ranks more than one option
- Reading, one loan an offer of open type may mean; AwaitingOffer, an offer whose type awaits
  the lender's answer, with its readings

Money is Decimal. Datetimes are timezone-aware UTC.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast, get_args

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

    def has_figures(self) -> bool:
        """The person has told at least one figure, by taking the help path for the ceiling."""
        return len(self.missing()) < len(_MONEY_FIELDS)

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


# The first payment the term card assumes when it proposes a term for a check with no ceiling.
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


# How a loan's rate today stands against the published average rate on consumer loans: the
# engine calls it similar within a set band of percentage points.
RateAgainstMarket = Literal["above", "similar", "below"]


@dataclass(frozen=True)
class OptionPrice:
    """The loan's rate today against the market, as the engine priced it."""

    rate_today: Decimal
    """The annual percent charged in the first month; on top of the CPI for a linked loan."""
    against_market: RateAgainstMarket | None
    """None for a CPI-linked loan, whose rate is not comparable with the unlinked average."""
    market_rate: Decimal
    """The Bank of Israel average annual percent on new unlinked household consumer loans."""
    market_rate_month: date

    def to_json(self) -> dict[str, str | None]:
        return {
            "rate_today": str(self.rate_today),
            "against_market": self.against_market,
            "market_rate": str(self.market_rate),
            "market_rate_month": self.market_rate_month.isoformat(),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "OptionPrice":
        against = data["against_market"]
        if against is not None and against not in get_args(RateAgainstMarket):
            raise ValueError(f"Unknown rate comparison: {against!r}")
        return cls(
            rate_today=Decimal(data["rate_today"]),
            against_market=against,
            market_rate=Decimal(data["market_rate"]),
            market_rate_month=date.fromisoformat(data["market_rate_month"]),
        )


@dataclass(frozen=True)
class OptionFigures:
    first_payment: Decimal
    peak_payment: Decimal
    worst_peak_payment: Decimal | None
    worst_start: date | None
    worst_end: date | None
    total_paid_low: Decimal | None
    total_paid_high: Decimal | None
    """The lowest and highest total repaid across the historical windows; None, like the worst
    window, for a payment that never moves."""
    balloon_due: Decimal | None
    total_paid: Decimal
    rate_as_of: date
    cpi_as_of: date
    price: OptionPrice | None
    """None when the stored figures hold no price: those of an option saved by a release whose
    engine reported no rates."""

    @property
    def risk_payment(self) -> Decimal:
        if self.worst_peak_payment is not None:
            return self.worst_peak_payment
        return self.peak_payment

    def to_json(self) -> dict[str, object]:
        """The one encoding of the figures, stored and sent to the page alike: money as decimal
        strings, dates as ISO strings."""
        return {
            "first_payment": str(self.first_payment),
            "peak_payment": str(self.peak_payment),
            "worst_peak_payment": _text_or_none(self.worst_peak_payment),
            "worst_start": _iso_or_none(self.worst_start),
            "worst_end": _iso_or_none(self.worst_end),
            "total_paid_low": _text_or_none(self.total_paid_low),
            "total_paid_high": _text_or_none(self.total_paid_high),
            "balloon_due": _text_or_none(self.balloon_due),
            "total_paid": str(self.total_paid),
            "rate_as_of": self.rate_as_of.isoformat(),
            "cpi_as_of": self.cpi_as_of.isoformat(),
            "price": None if self.price is None else self.price.to_json(),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "OptionFigures":
        # price is the one key stored figures may lack.
        price = data.get("price")
        return cls(
            first_payment=Decimal(data["first_payment"]),
            peak_payment=Decimal(data["peak_payment"]),
            worst_peak_payment=_decimal_or_none(data["worst_peak_payment"]),
            worst_start=_date_or_none(data["worst_start"]),
            worst_end=_date_or_none(data["worst_end"]),
            total_paid_low=_decimal_or_none(data["total_paid_low"]),
            total_paid_high=_decimal_or_none(data["total_paid_high"]),
            balloon_due=_decimal_or_none(data["balloon_due"]),
            total_paid=Decimal(data["total_paid"]),
            rate_as_of=date.fromisoformat(data["rate_as_of"]),
            cpi_as_of=date.fromisoformat(data["cpi_as_of"]),
            price=None if price is None else OptionPrice.from_json(price),
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

    @property
    def principal(self) -> Decimal:
        """The loan's total principal; a saved loan's principals are decimal strings or
        integers."""
        tracks = cast(list[Mapping[str, object]], self.loan["tracks"])
        return sum((Decimal(cast(str | int, track["principal"])) for track in tracks), Decimal(0))

    @property
    def interest_cost(self) -> Decimal:
        """What the loan costs over its principal at today's terms: its total paid on the base
        path minus the principal, so for a linked loan the CPI's rise is in it too."""
        return self.summary.total_paid - self.principal

    def for_term(self, term_months: int | None) -> bool:
        """Whether the option is one for the check's term: an offer always is, since the term's
        save prices an open offer at it; an example is when every track runs for the term."""
        if term_months is None or self.source == "offer":
            return True
        tracks = cast(list[Mapping[str, object]], self.loan["tracks"])
        return all(track["term_months"] == term_months for track in tracks)


def compares_options(
    options: Iterable[Option], named_ids: Collection[str], term_months: int | None
) -> bool:
    """Whether a recommendation compares more than one option: the options its card shows, those
    it names and every other one for the check's term, number more than one. One option alone
    is evaluated, not recommended."""
    shown = [option for option in options if option.id in named_ids or option.for_term(term_months)]
    return len(shown) > 1


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

    @property
    def named_option_ids(self) -> tuple[str, ...]:
        """The preferred option's id, then the alternative's when there is one."""
        if self.alternative_option_id is None:
            return (self.preferred_option_id,)
        return (self.preferred_option_id, self.alternative_option_id)


# The loans an offer of open type may mean, in the order its card lists them. prime_margin is
# prime plus the stated number, prime_total prices prime at the stated number's total rate
# today, fixed_unlinked and fixed_linked are a fixed rate without and with linkage to the CPI.
ReadingKind = Literal["prime_margin", "prime_total", "fixed_unlinked", "fixed_linked"]
_READING_KINDS: tuple[str, ...] = get_args(ReadingKind)
# The words of an offer that name its type, which the offer says in Hebrew.
TypeWord = Literal["prime", "fixed", "linked"]


@dataclass(frozen=True)
class Reading:
    kind: ReadingKind
    track: Mapping[str, object]
    """The engine's Track arguments of this reading's loan."""
    first_payment: Decimal
    total_rate: Decimal
    """The annual percent charged today."""
    approximate: bool
    """Set for the linked reading of an offer that quotes only its payment, whose rate is the one
    that gives the payment unlinked."""

    def to_json(self) -> dict[str, object]:
        """The one encoding of a reading, in the engine's results, the events and the store."""
        return {
            "kind": self.kind,
            "track": dict(self.track),
            "first_payment": str(self.first_payment),
            "total_rate": str(self.total_rate),
            "approximate": self.approximate,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Reading":
        kind = data["kind"]
        if kind not in _READING_KINDS:
            raise ValueError(f"Unknown reading kind: {kind!r}")
        return cls(
            kind=kind,
            track=data["track"],
            first_payment=Decimal(data["first_payment"]),
            total_rate=Decimal(data["total_rate"]),
            approximate=data["approximate"],
        )


@dataclass(frozen=True)
class AwaitingOffer:
    """A lender's offer that waits on its lender's answer, kept with its readings: one whose words
    leave its type open, until the person tells which reading the lender meant, or one quoted for
    less than the check's loan, until the lender says whether it lends the loan amount on the
    same terms. The offer states a rate, quotes a payment, or both."""

    id: str
    check_id: str
    lender: str
    amount: Decimal
    """The amount the lender quoted, which may differ from the check's loan."""
    term_months: int
    stated_rate: Decimal | None
    monthly_payment: Decimal | None
    payment_rate: Decimal | None
    """The fixed rate that gives monthly_payment; None when the offer quotes no payment."""
    type_words: tuple[TypeWord, ...]
    readings: tuple[Reading, ...]
    likely: ReadingKind | None
    """The reading the offer's words point to, when they point to one."""
    prime: Decimal
    rate_as_of: date
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc("created_at", self.created_at)
