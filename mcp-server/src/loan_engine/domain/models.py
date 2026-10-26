"""Input models of the loan engine, which double as the MCP tool schemas.

- Track: one slice of a loan with its own rate, term and repayment method
- Loan: one or more tracks borrowed together
- Profile: the borrower's monthly income and obligations
"""

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from loan_engine.domain.limits import (
    MAX_ANNUAL_RATE,
    MAX_PRIME_SPREAD,
    MAX_PRINCIPAL,
    MAX_TERM,
    MIN_ANNUAL_RATE,
    MIN_PRIME_SPREAD,
    MIN_PRINCIPAL,
    MIN_TERM,
)

RateKind = Literal["fixed", "prime"]
Method = Literal["spitzer", "equal_principal", "balloon"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Track(_Model):
    principal: Decimal = Field(gt=0, le=MAX_PRINCIPAL)
    term_months: int = Field(ge=MIN_TERM, le=MAX_TERM)
    rate_kind: RateKind
    annual_rate: Decimal | None = Field(
        default=None,
        ge=MIN_ANNUAL_RATE,
        le=MAX_ANNUAL_RATE,
        description="Nominal annual percent; fixed tracks only",
    )
    prime_spread: Decimal | None = Field(
        default=None,
        ge=MIN_PRIME_SPREAD,
        le=MAX_PRIME_SPREAD,
        description="Percent over prime; prime tracks only",
    )
    cpi_linked: bool
    method: Method
    balloon_amount: Decimal = Field(default=Decimal(0), ge=0)
    one_time_fee: Decimal = Field(default=Decimal(0), ge=0)
    monthly_fee: Decimal = Field(default=Decimal(0), ge=0)

    @model_validator(mode="after")
    def _check_rate_fields(self) -> Self:
        if self.rate_kind == "fixed":
            if self.annual_rate is None:
                raise ValueError("annual_rate is required when rate_kind is 'fixed'")
            if self.prime_spread is not None:
                raise ValueError("prime_spread must be omitted when rate_kind is 'fixed'")
        else:
            if self.prime_spread is None:
                raise ValueError("prime_spread is required when rate_kind is 'prime'")
            if self.annual_rate is not None:
                raise ValueError("annual_rate must be omitted when rate_kind is 'prime'")
        return self

    @model_validator(mode="after")
    def _check_balloon(self) -> Self:
        if self.method == "balloon" and self.balloon_amount == 0:
            raise ValueError("balloon_amount must be above 0 when method is 'balloon'")
        if self.method != "balloon" and self.balloon_amount != 0:
            raise ValueError("balloon_amount must be 0 unless method is 'balloon'")
        if self.balloon_amount >= self.principal:
            raise ValueError("balloon_amount must be below principal")
        return self


class Loan(_Model):
    tracks: list[Track] = Field(min_length=1)

    @property
    def principal(self) -> Decimal:
        return sum((track.principal for track in self.tracks), Decimal(0))

    @model_validator(mode="after")
    def _check_principal_limits(self) -> Self:
        if not MIN_PRINCIPAL <= self.principal <= MAX_PRINCIPAL:
            raise ValueError(
                f"principal (the sum of the tracks' principal) is {self.principal}, "
                f"must be between {MIN_PRINCIPAL} and {MAX_PRINCIPAL}"
            )
        return self


class Profile(_Model):
    net_fixed_income: Decimal = Field(ge=0)
    variable_income: Decimal = Field(ge=0)
    variable_income_stable: bool
    fixed_expenses: Decimal = Field(ge=0)
    existing_loan_payments: Decimal = Field(ge=0)
