"""The loan engine as the application sees it: affordability, sizing, simulation, suggested
tracks and the market data, with money as Decimal.

- LoanEngine: the engine calls
- Bounds, Sizing, Simulation, OfferTerm, MarketSeries: their parsed results
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
    min_cushion: Decimal
    reasons: tuple[str, ...]
    """The engine's reason codes for how the ceiling was set, in order."""


@dataclass(frozen=True)
class Sizing:
    loan_amount: Decimal
    """May be 0, below the engine's minimum loan, or above its maximum loan: the engine sizes
    what the purchase needs, not what it can price."""
    savings_used: Decimal
    cushion_kept: Decimal
    spare_savings: Decimal


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
        """profile: the engine's Profile arguments, as Profile.engine_profile() gives them."""
        ...

    async def size(self, goal_price: Decimal, savings: Decimal, min_cushion: Decimal) -> Sizing: ...

    async def simulate(self, loan: Mapping[str, object]) -> Simulation:
        """loan: the engine's Loan arguments; the agent prices one-track loans only."""
        ...

    async def suggest(self, principal: Decimal, term_months: int) -> list[Mapping[str, object]]:
        """A fixed and a prime track, as engine Loan track arguments."""
        ...

    async def offer_term(self, track: Mapping[str, object], payment_ceiling: Decimal) -> OfferTerm:
        """track: an engine Loan track whose term_months is the longest the offer allows."""
        ...

    async def market_series(self, months: int) -> MarketSeries:
        """The latest months of the prime and of the CPI's monthly change."""
        ...
