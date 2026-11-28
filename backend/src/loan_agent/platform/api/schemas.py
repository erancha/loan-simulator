"""The JSON bodies of the checks routes. Money travels as decimal strings, both ways,
so no amount passes through a binary float; dates and datetimes are ISO strings."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from loan_agent.application.check_tools import MAX_TERM, MIN_TERM
from loan_agent.domain.models import (
    AwaitingOffer,
    CeilingSource,
    Check,
    Finances,
    LoanRequest,
    Option,
    OptionFigures,
    OptionSource,
    ReadingKind,
)
from loan_agent.domain.models import Recommendation as DomainRecommendation


class CreatedCheck(BaseModel):
    id: str


class RecommendationSummary(BaseModel):
    preferred_option_id: str
    alternative_option_id: str | None
    loan_amount: Decimal
    payment_ceiling: Decimal | None
    checked: bool
    """The recommendation was checked against a payment ceiling."""
    created_at: datetime

    @classmethod
    def of(cls, recommendation: DomainRecommendation) -> Self:
        return cls.model_validate(recommendation, from_attributes=True)


class Recommendation(RecommendationSummary):
    reasoning: str


class AwaitingSummary(BaseModel):
    """An offer that awaits its lender's answer, as the checks list links to it."""

    id: str
    lender: str
    monthly_payment: Decimal | None

    @classmethod
    def of(cls, offer: AwaitingOffer) -> Self:
        return cls(id=offer.id, lender=offer.lender, monthly_payment=offer.monthly_payment)


class CheckSummary(BaseModel):
    id: str
    created_at: datetime
    loan: LoanRequest | None
    term_months: int | None
    """The term the person confirmed; None until then."""
    recommendation: RecommendationSummary | None
    recommends_examples_only: bool
    """Every option the recommendation names is an example nobody can take."""
    compares_options: bool
    """The recommendation's card shows more than one option, so it ranks them; one option alone
    is evaluated, not recommended. False without a recommendation."""
    archived: bool
    """Closed by the person; the check is read-only until restored."""
    started: bool
    """The person has sent the check a message; before that it shows only the opening card."""
    has_finances: bool
    """The check holds a payment ceiling or a finances figure: something its finances line
    shows."""
    awaiting_offers: list[AwaitingSummary]
    """Oldest first."""

    @classmethod
    def of(
        cls,
        check: Check,
        recommendation: DomainRecommendation | None,
        recommends_examples_only: bool,
        compares_options: bool,
        started: bool,
        awaiting: list[AwaitingOffer],
    ) -> Self:
        return cls(
            id=check.id,
            created_at=check.created_at,
            loan=check.loan,
            term_months=check.term_months,
            recommendation=None
            if recommendation is None
            else RecommendationSummary.of(recommendation),
            recommends_examples_only=recommends_examples_only,
            compares_options=compares_options,
            archived=check.archived_at is not None,
            started=started,
            has_finances=check.payment_ceiling is not None or check.finances.has_figures(),
            awaiting_offers=[AwaitingSummary.of(offer) for offer in awaiting],
        )


class OptionView(BaseModel):
    id: str
    source: OptionSource
    lender: str | None
    offer_date: date | None
    max_term_months: int | None
    """The longest term a real offer allows, when it leaves the term open."""
    loan: dict[str, Any]
    """The engine's Loan arguments the option was priced with."""
    figures: OptionFigures
    created_at: datetime

    @classmethod
    def of(cls, option: Option) -> Self:
        return cls(
            id=option.id,
            source=option.source,
            lender=option.lender,
            offer_date=option.offer_date,
            max_term_months=option.max_term_months,
            loan=dict(option.loan),
            figures=option.summary,
            created_at=option.created_at,
        )


class CheckView(BaseModel):
    id: str
    created_at: datetime
    loan: LoanRequest | None
    term_months: int | None
    payment_ceiling: Decimal | None
    ceiling_source: CeilingSource | None
    finances: Finances
    options: list[OptionView]
    """Oldest first."""
    recommendation: Recommendation | None
    archived: bool

    @classmethod
    def of(
        cls, check: Check, options: list[Option], recommendation: DomainRecommendation | None
    ) -> Self:
        return cls(
            id=check.id,
            created_at=check.created_at,
            loan=check.loan,
            term_months=check.term_months,
            payment_ceiling=check.payment_ceiling,
            ceiling_source=check.ceiling_source,
            finances=check.finances,
            options=[OptionView.of(option) for option in options],
            recommendation=None if recommendation is None else Recommendation.of(recommendation),
            archived=check.archived_at is not None,
        )


class Message(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("text is empty")
        return text


class FormTrack(BaseModel):
    """One track of the offer form: the annual percent of a fixed track, or the margin over prime
    of a prime one, negative under prime."""

    rate_kind: Literal["fixed", "prime"]
    rate: Decimal
    cpi_linked: bool


class FormOffer(BaseModel):
    """An offer the page's form filled in, with the line the chat shows for it."""

    line: str = Field(min_length=1)
    lender: str = Field(min_length=1)
    tracks: list[FormTrack] = Field(min_length=1)
    max_term_months: int = Field(ge=MIN_TERM, le=MAX_TERM)


class ChatMessage(BaseModel):
    """What the person sends in the chat: free text the model reads, or an offer from the form,
    which the server saves before the turn; never both."""

    text: str | None = None
    offer: FormOffer | None = None

    @model_validator(mode="after")
    def _text_or_offer(self) -> Self:
        if (self.text is None) == (self.offer is None):
            raise ValueError("send either text or offer")
        if self.text is not None and not self.text.strip():
            raise ValueError("text is empty")
        return self


class Opening(Message):
    """The opening card's goal and amount, with the line that tells them."""

    purpose: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)


class TermCeiling(Message):
    """A payment ceiling the person typed on the term card, with the line that tells it."""

    payment_ceiling: Decimal = Field(gt=0)


class TermConfirmation(BaseModel):
    """The term confirmed on the term card, with the payment ceiling typed beside it, if any."""

    term_months: int = Field(ge=MIN_TERM, le=MAX_TERM)
    payment_ceiling: Decimal | None = Field(default=None, gt=0)


class ReadingConfirmation(BaseModel):
    """The reading the person confirms on an awaiting offer's card."""

    reading: ReadingKind


class AmountAnswer(BaseModel):
    """The lender's answer to an offer quoted for less than the check's loan: whether it lends the
    loan amount on the same terms, with the reading chosen on a card of several."""

    covers: bool
    reading: ReadingKind | None = None


class FinancesUpdate(BaseModel):
    """The figures to replace; a figure left out keeps its value."""

    model_config = ConfigDict(extra="forbid")

    net_fixed_income: str | None = None
    fixed_expenses: str | None = None

    def sent(self) -> dict[str, object]:
        """The figures the body named, an explicit null included, which the finances refuse."""
        return self.model_dump(exclude_unset=True)
