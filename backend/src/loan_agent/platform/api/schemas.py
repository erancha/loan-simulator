"""The JSON bodies of the checks and profile routes. Money travels as decimal strings, both ways,
so no amount passes through a binary float; dates and datetimes are ISO strings."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator

from loan_agent.domain.models import Check, Goal, Option, OptionFigures, OptionSource, Profile
from loan_agent.domain.models import Recommendation as DomainRecommendation


class CreatedCheck(BaseModel):
    id: str


class RecommendationSummary(BaseModel):
    preferred_option_id: str
    alternative_option_id: str | None
    loan_amount: Decimal
    payment_ceiling: Decimal
    created_at: datetime

    @classmethod
    def of(cls, recommendation: DomainRecommendation) -> Self:
        return cls.model_validate(recommendation, from_attributes=True)


class Recommendation(RecommendationSummary):
    reasoning: str
    min_cushion: Decimal
    cushion_kept: Decimal


class CheckSummary(BaseModel):
    id: str
    created_at: datetime
    goal: Goal | None
    recommendation: RecommendationSummary | None
    recommends_examples_only: bool
    """Every option the recommendation names is an example nobody can take."""
    profile_stale: bool

    @classmethod
    def of(
        cls,
        check: Check,
        recommendation: DomainRecommendation | None,
        recommends_examples_only: bool,
        profile_stale: bool,
    ) -> Self:
        return cls(
            id=check.id,
            created_at=check.created_at,
            goal=check.goal,
            recommendation=None
            if recommendation is None
            else RecommendationSummary.of(recommendation),
            recommends_examples_only=recommends_examples_only,
            profile_stale=profile_stale,
        )


class OptionView(BaseModel):
    id: str
    source: OptionSource
    lender: str | None
    offer_date: date | None
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
            loan=dict(option.loan),
            figures=option.summary,
            created_at=option.created_at,
        )


class CheckView(BaseModel):
    id: str
    created_at: datetime
    goal: Goal | None
    options: list[OptionView]
    """Oldest first."""
    recommendation: Recommendation | None
    profile_stale: bool
    """The profile was saved after the version the recommendation was computed from."""


class Message(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("text is empty")
        return text


class ProfileView(BaseModel):
    profile: Profile
    missing: list[str]
    """The fields the person has not told yet."""

    @classmethod
    def of(cls, profile: Profile) -> Self:
        return cls(profile=profile, missing=list(profile.missing()))


class ProfileUpdate(BaseModel):
    """The fields to replace; a field left out keeps its value."""

    model_config = ConfigDict(extra="forbid")

    savings: str | None = None
    net_fixed_income: str | None = None
    variable_income: str | None = None
    variable_income_minimum: str | None = None
    fixed_expenses: str | None = None
    existing_loan_payments: str | None = None

    def sent(self) -> dict[str, object]:
        """The fields the body named, an explicit null included, which the profile refuses."""
        return self.model_dump(exclude_unset=True)
