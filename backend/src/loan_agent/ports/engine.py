"""The loan engine as the application sees it: affordability, simulation, suggested tracks, the
ceiling searches (terms and the largest loan) and the market data, with money as Decimal.

- LoanEngine: the engine calls
- Bounds, Simulation, OfferTerm, ProposedTerm, MarketSeries: their parsed results
- EngineError: a call the engine refused, or a loan of more than one track, which the agent does
  not price yet; the message names the fault
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from loan_agent.domain.models import OptionFigures


class EngineError(Exception):
    pass


@dataclass(frozen=True)
class Bounds:
    payment_ceiling: Decimal
    """The lower of the two caps below, never below zero."""
    income_share: Decimal
    ceiling_by_income_share: Decimal
    """income_share, a fraction, of the net fixed income."""
    disposable_share: Decimal
    ceiling_by_disposable_income: Decimal
    """disposable_share, a fraction, of the net fixed income minus the fixed expenses."""
    reasons: tuple[str, ...]
    """The engine's reason codes for how the ceiling was set, in order."""


@dataclass(frozen=True)
class Simulation:
    figures: OptionFigures
    structured: Mapping[str, object]
    """The engine's full result, month-by-month schedules included, for the page."""


@dataclass(frozen=True)
class OfferTerm:
    term_months: int
    """The shortest comfortable term of an offer, or its longest term when none is comfortable."""
    comfortable: bool


@dataclass(frozen=True)
class ProposedTerm:
    term_months: int
    first_payment: Decimal
    """The first payment at term_months; the higher of the two example tracks' for a loan
    without an offer."""


@dataclass(frozen=True)
class MarketPoint:
    month: date
    value: Decimal


@dataclass(frozen=True)
class MarketSeries:
    """The latest months of each series, oldest first."""

    prime: tuple[MarketPoint, ...]
    """The prime in annual percent in effect on the first of each month."""
    rate_as_of: date
    cpi_change: tuple[MarketPoint, ...]
    """Each month's change of the consumer price index, percent."""
    cpi_as_of: date


@runtime_checkable
class LoanEngine(Protocol):
    async def assess(self, profile: Mapping[str, object]) -> Bounds:
        """profile: the engine's Profile arguments (net_fixed_income, fixed_expenses)."""
        ...

    async def simulate(self, loan: Mapping[str, object]) -> Simulation:
        """loan: the engine's Loan arguments; the agent prices one-track loans only."""
        ...

    async def suggest(self, principal: Decimal, term_months: int) -> list[Mapping[str, object]]:
        """A fixed and a prime track, as engine Loan track arguments."""
        ...

    async def offer_term(self, track: Mapping[str, object], payment_ceiling: Decimal) -> OfferTerm:
        """track: an engine Loan track whose term_months is the longest the offer allows."""
        ...

    async def propose_term(self, principal: Decimal, payment_limit: Decimal) -> ProposedTerm:
        """The shortest term at which the example tracks both start below payment_limit."""
        ...

    async def propose_offer_term(
        self, track: Mapping[str, object], payment_limit: Decimal
    ) -> ProposedTerm:
        """track: an engine Loan track whose term_months is the longest the offer allows."""
        ...

    async def comfortable_term(
        self, principal: Decimal, payment_ceiling: Decimal, *, any_track: bool
    ) -> int | None:
        """The shortest term whose highest payment stays within the ceiling, on every example
        track or, with any_track, on at least one; None when no term the engine prices fits."""
        ...

    async def largest_loan(self, payment_ceiling: Decimal, term_months: int) -> Decimal | None:
        """The largest loan the ceiling carries at the term; None when even the smallest loan
        the engine prices does not fit."""
        ...

    async def market_series(self, months: int) -> MarketSeries:
        """The latest months of the prime and of the CPI's monthly change."""
        ...
