"""The loan engine as the application sees it: affordability, simulation, suggested tracks, the
ceiling searches (terms and the largest loan), the readings of an offer of open type and the
market data, with money as Decimal.

- LoanEngine: the engine calls
- Bounds, Simulation, ScenarioFigures, OfferTerm, ProposedTerm, OfferReadings, MarketSeries:
  their parsed results
- EngineError: a call the engine refused, or a loan of more than one track, which the agent does
  not price yet; the message names the fault
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from loan_agent.domain.models import OptionFigures, Reading


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
class ScenarioFigures:
    """A loan priced on a scenario, with the scenario as the engine filled it in: an unnamed
    value is the engine's default."""

    cpi_per_year: Decimal
    prime_per_year: Decimal
    cpi_like_last_years: int | None
    """The years cpi_per_year averages, when the person described the CPI as the last years."""
    prime_like_last_years: int | None
    first_payment: Decimal
    max_payment: Decimal
    total_paid: Decimal


@dataclass(frozen=True)
class OfferTerm:
    term_months: int
    """The shortest comfortable term of an offer, or its longest term when none is comfortable."""
    comfortable: bool


@dataclass(frozen=True)
class ProposedTerm:
    term_months: int
    first_payment: Decimal
    """The first payment at term_months; the higher of the two unlinked example tracks' for a
    loan without an offer."""


@dataclass(frozen=True)
class OfferReadings:
    prime: Decimal
    """The prime in annual percent the readings are priced at."""
    rate_as_of: date
    payment_rate: Decimal | None
    """The fixed rate that gives the offer's monthly payment; None for an offer without one."""
    readings: tuple[Reading, ...]
    """In the order the offer's card lists them."""


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
    consumer_rate: Decimal
    """The Bank of Israel's latest average rate on new household consumer loans, annual percent:
    the fixed example track's rate, and the rate the prime example's margin is set from."""
    consumer_rate_month: date


@runtime_checkable
class LoanEngine(Protocol):
    async def assess(self, profile: Mapping[str, object]) -> Bounds:
        """profile: the engine's Profile arguments (net_fixed_income, fixed_expenses)."""
        ...

    async def simulate(self, loan: Mapping[str, object]) -> Simulation:
        """loan: the engine's Loan arguments; the agent prices one-track loans only."""
        ...

    async def suggest(self, principal: Decimal, term_months: int) -> list[Mapping[str, object]]:
        """A fixed and a prime track, both unlinked, then a pension fund's fixed track linked to
        the CPI, as engine Loan track arguments."""
        ...

    async def offer_term(self, track: Mapping[str, object], payment_ceiling: Decimal) -> OfferTerm:
        """track: an engine Loan track whose term_months is the longest the offer allows."""
        ...

    async def propose_term(self, principal: Decimal, payment_limit: Decimal) -> ProposedTerm:
        """The shortest term at which the unlinked example tracks both start below
        payment_limit."""
        ...

    async def propose_offer_term(
        self, track: Mapping[str, object], payment_limit: Decimal
    ) -> ProposedTerm:
        """track: an engine Loan track whose term_months is the longest the offer allows."""
        ...

    async def comfortable_term(
        self, principal: Decimal, payment_ceiling: Decimal, *, any_track: bool
    ) -> int | None:
        """The shortest term whose highest payment stays within the ceiling, on both unlinked
        example tracks or, with any_track, on at least one; None when no term the engine prices
        fits."""
        ...

    async def largest_loan(self, payment_ceiling: Decimal, term_months: int) -> Decimal | None:
        """The largest loan the ceiling carries at the term on an unlinked example track; None
        when even the smallest loan the engine prices does not fit."""
        ...

    async def offer_readings(
        self,
        principal: Decimal,
        term_months: int,
        stated_rate: Decimal | None,
        monthly_payment: Decimal | None,
        *,
        prime_total: bool,
    ) -> OfferReadings:
        """The loans an offer of open type may mean: from stated_rate when it is given, with
        prime_total also as prime's total rate today, otherwise from monthly_payment."""
        ...

    async def market_series(self, months: int) -> MarketSeries:
        """The latest months of the prime and of the CPI's monthly change."""
        ...

    async def simulate_scenario(
        self, loan: Mapping[str, object], scenario: Mapping[str, object]
    ) -> ScenarioFigures:
        """The loan priced on the scenario the person named: cpi_per_year and prime_per_year as
        decimal strings, or cpi_like_last_years and prime_like_last_years as years, each left out
        when the person did not name it."""
        ...
