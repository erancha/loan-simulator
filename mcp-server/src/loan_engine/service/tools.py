"""The loan-engine tools, described for a language model, with money rounded to agorot
(hundredths of a shekel).

- Output models: Bounds, Sizing, LoanSimulation (TrackSimulation, MonthRow), ComfortableTerm,
  OfferTerm, TrackSuggestions, MarketSeries (PrimeMonth, CpiMonth)
- register_tools(): adds the tools to a server; each reads market data from history_provider

simulate_loan returns its LoanSimulation as structured content and only a short summary as text,
so the agent will be able to pass the schedule to the page without it filling the model's context.

Argument validation failures and the domain's NoHistoryWindowError reach the caller as tool errors
whose message names the field or the term at fault; the MCP SDK withholds the text of any other
exception.
"""

from collections.abc import Callable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from loan_engine.domain import history, policy, schedule
from loan_engine.domain.assumptions import (
    BASE_ANNUAL_INFLATION,
    COMFORT_SHARE,
    HISTORY_MONTHS,
    PRIME_MARGIN,
)
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
from loan_engine.domain.models import Loan, Profile, Track
from loan_engine.market.boi import CONSUMER_RATE_SERIES

_AGOROT = Decimal("0.01")


def _to_agorot(value: Decimal) -> Decimal:
    return value.quantize(_AGOROT, rounding=ROUND_HALF_UP)


Money = Annotated[Decimal, AfterValidator(_to_agorot)]

_BASE_PATH = (
    f"the base path: today's rates held flat and, for CPI-linked tracks, "
    f"{BASE_ANNUAL_INFLATION}% annual inflation"
)

_PROFILE = (
    "The person's monthly finances, every amount in ₪ per month: net_fixed_income (salary after "
    "tax), variable_income (bonuses, commissions, freelance work), variable_income_minimum (the "
    "part of the variable income that arrives even in a weak month, at most variable_income; "
    "only this part counts toward the payment limit), fixed_expenses (rent, "
    "bills and other recurring spending), existing_loan_payments (payments on loans already "
    "running)."
)

_LOAN = (
    "The loan as one or more tracks. Per track: principal in ₪; term_months in months "
    f"({MIN_TERM}-{MAX_TERM}); rate_kind 'fixed' with annual_rate (annual percent, "
    f"{MIN_ANNUAL_RATE} to {MAX_ANNUAL_RATE}: 7.9 means 7.9%), or 'prime' with prime_spread "
    f"(annual percent over prime, {MIN_PRIME_SPREAD} to {MAX_PRIME_SPREAD}), omitting the other "
    "rate field; cpi_linked "
    "true when the balance is indexed to the consumer price index; method 'spitzer' (equal "
    "payments), 'equal_principal', or 'balloon' with balloon_amount (₪ repaid in the last month, "
    "above 0 and below principal); one_time_fee and monthly_fee in ₪. The tracks' principal sums "
    f"to {MIN_PRINCIPAL:,}-{MAX_PRINCIPAL:,} ₪."
)


class _Output(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)


class Bounds(_Output):
    payment_ceiling: Money = Field(
        description="Highest monthly loan payment the person can carry, ₪ per month"
    )
    min_cushion: Money = Field(description="Savings the person keeps untouched, ₪")
    counted_income: Money = Field(description="Monthly income the ceiling is based on, ₪ per month")
    reasons: list[policy.Reason] = Field(description="How the ceiling was set, in order")


class Sizing(_Output):
    loan_amount: Money = Field(
        description=f"Amount to borrow, ₪; may be 0 or below the {MIN_PRINCIPAL:,} ₪ minimum loan"
    )
    savings_used: Money = Field(description="Savings put toward the price, ₪")
    cushion_kept: Money = Field(description="Savings kept as the cushion, ₪")
    spare_savings: Money = Field(description="Savings left over after the price is covered, ₪")


class MonthRow(_Output):
    month: int = Field(description="Month number, 1 being the first payment")
    annual_rate: Decimal = Field(description="Annual percent applied this month")
    payment: Money = Field(description="Payment this month including the monthly fee, ₪")
    interest: Money = Field(description="Interest charged this month, ₪")
    principal: Money = Field(description="Principal repaid this month, ₪")
    balance: Money = Field(description="Balance after this month's payment, ₪")


_BALLOON_DUE = (
    "Balloon cleared in the last month on top of that month's recurring payment, ₪; null when the "
    "track has no balloon"
)


class Window(_Output):
    start: date = Field(description="First month of the historical window")
    end: date = Field(description="Last month of the historical window")
    max_payment: Money = Field(
        description="Highest recurring monthly payment in this window, without the balloon, ₪"
    )
    balloon_due: Money | None = Field(description=f"{_BALLOON_DUE}; indexed by this window's CPI")
    total_paid: Money = Field(description="Total repaid in this window, ₪")


class MoneyRange(_Output):
    low: Money
    high: Money


class TrackSimulation(_Output):
    first_payment: Money = Field(description=f"Payment in month 1 on {_BASE_PATH}, ₪")
    max_base_payment: Money = Field(
        description=f"Highest recurring monthly payment on {_BASE_PATH}, without the balloon, ₪"
    )
    balloon_due: Money | None = Field(description=f"{_BALLOON_DUE}; on {_BASE_PATH}")
    total_paid: Money = Field(
        description=f"Total repaid on {_BASE_PATH}, including fees and the balloon, ₪"
    )
    worst: Window | None = Field(
        description="Historical window with the highest peak recurring payment; null for a fixed "
        "unlinked track, whose payment cannot move"
    )
    max_payment_range: MoneyRange | None = Field(
        description="Lowest and highest peak recurring monthly payment across the historical "
        "windows, ₪"
    )
    total_paid_range: MoneyRange | None = Field(
        description="Lowest and highest total repaid across the historical windows, ₪"
    )
    windows: int = Field(description="Number of historical windows replayed")
    schedule: list[MonthRow] = Field(description=f"Month by month on {_BASE_PATH}")

    @classmethod
    def of(cls, outcome: history.TrackOutcome) -> "TrackSimulation":
        return cls(
            first_payment=outcome.base.first_payment,
            max_base_payment=outcome.base.max_payment,
            balloon_due=outcome.base.balloon_due,
            total_paid=outcome.base.total_paid,
            worst=None if outcome.worst is None else Window.model_validate(outcome.worst),
            max_payment_range=_range(outcome.max_payment_range),
            total_paid_range=_range(outcome.total_paid_range),
            windows=outcome.windows,
            schedule=[MonthRow.model_validate(row) for row in outcome.base.rows],
        )


class LoanSimulation(_Output):
    tracks: list[TrackSimulation] = Field(description="One result per track, in input order")
    first_payment: Money = Field(
        description=f"Today's monthly payment of the whole loan on {_BASE_PATH}, ₪"
    )
    max_base_payment: Money = Field(
        description=f"Highest recurring monthly payment of the whole loan on {_BASE_PATH}, "
        "without the tracks' balloons, ₪"
    )
    total_paid: Money = Field(description=f"Total repaid for the whole loan on {_BASE_PATH}, ₪")
    rate_as_of: date = Field(description="Date of the Bank of Israel rate used")
    cpi_as_of: date = Field(description="Month of the latest consumer price index used")


class ComfortableTerm(_Output):
    term_months: int = Field(description="The shortest comfortable term, months")
    payment_limit: Money = Field(
        description="The most the payment may reach at that term: 90% of the ceiling, ₪ per month"
    )


class OfferTerm(_Output):
    term_months: int = Field(
        description="The term to price the offer at: the shortest comfortable term, or the "
        "offer's longest term when none is comfortable"
    )
    comfortable: bool = Field(description="Whether term_months keeps the payment within the limit")
    payment_limit: Money = Field(
        description="The most a comfortable payment may reach: 90% of the ceiling, ₪ per month"
    )


class TrackSuggestions(_Output):
    tracks: list[Track] = Field(description="A fixed track and a prime track, both unlinked")
    as_of: date = Field(description="Month of the average rate the tracks are priced from")
    source: str


class PrimeMonth(_Output):
    month: date
    prime: Decimal = Field(description="Prime in annual percent in effect on the first of month")


class CpiMonth(_Output):
    month: date
    change_percent: Decimal = Field(
        description="That month's change of the consumer price index, percent, to one decimal"
    )


class MarketSeries(_Output):
    current_prime: Decimal = Field(description="Today's prime, annual percent")
    rate_as_of: date = Field(description="Date of the latest Bank of Israel rate")
    prime: list[PrimeMonth] = Field(
        description="The latest months, oldest first, ending with today's prime under the "
        "current month"
    )
    cpi_as_of: date = Field(description="Month of the latest consumer price index")
    cpi: list[CpiMonth] = Field(description="The latest months, oldest first")


_ONE_DECIMAL = Decimal("0.1")


def _summary(loan: LoanSimulation) -> str:
    lines = [f"Figures are on {_BASE_PATH}, except in a named historical window."]
    lines += [_track_summary(number, track) for number, track in enumerate(loan.tracks, start=1)]
    lines.append(
        f"Loan: first payment {loan.first_payment} ₪; peak recurring payment "
        f"{loan.max_base_payment} ₪; total repaid {loan.total_paid} ₪."
    )
    lines.append(
        f"Market data: Bank of Israel rate as of {loan.rate_as_of}, CPI as of "
        f"{loan.cpi_as_of:%Y-%m}. The month-by-month schedule is in the structured content."
    )
    return "\n".join(lines)


def _track_summary(number: int, track: TrackSimulation) -> str:
    parts = [
        f"first payment {track.first_payment} ₪",
        f"peak recurring payment {track.max_base_payment} ₪",
    ]
    if track.balloon_due is not None:
        parts.append(f"balloon of {track.balloon_due} ₪ due in the last month")
    parts.append(f"total repaid {track.total_paid} ₪")
    if track.worst is None:
        parts.append("no historical risk: a fixed unlinked payment cannot move")
    else:
        worst = track.worst
        risk = (
            f"worst of {track.windows} historical windows {worst.start:%Y-%m} to {worst.end:%Y-%m} "
            f"with peak recurring payment {worst.max_payment} ₪"
        )
        if worst.balloon_due is not None:
            risk += f" and a balloon of {worst.balloon_due} ₪"
        parts.append(risk)
    return f"Track {number}: " + "; ".join(parts) + "."


def _range(bounds: tuple[Decimal, Decimal] | None) -> MoneyRange | None:
    return None if bounds is None else MoneyRange(low=bounds[0], high=bounds[1])


def _monthly_totals(schedules: Sequence[schedule.Schedule]) -> list[Decimal]:
    """Summed recurring payment of all tracks for each month until the longest track ends."""
    payments = [s.recurring_payments for s in schedules]
    months = max(len(p) for p in payments)
    return [sum((p[m] for p in payments if m < len(p)), Decimal(0)) for m in range(months)]


def register_tools(
    server: MCPServer[Any], history_provider: Callable[[], history.MarketHistory]
) -> None:
    @server.tool()
    def assess_affordability(profile: Annotated[Profile, Field(description=_PROFILE)]) -> Bounds:
        """Call this once the person's monthly income and obligations are known, before any loan
        amount or payment is discussed. Returns the highest monthly payment the person can carry,
        the savings cushion to keep, the income counted, and reason codes for how they were set.
        """
        return Bounds.model_validate(policy.assess_affordability(profile))

    @server.tool()
    def size_loan(
        goal_price: Annotated[Decimal, Field(ge=0, description="Price of the purchase, ₪")],
        savings: Annotated[
            Decimal, Field(ge=0, description="The person's liquid money for the purchase, ₪")
        ],
        min_cushion: Annotated[
            Decimal,
            Field(
                ge=0, description="Savings to keep untouched, ₪: assess_affordability's min_cushion"
            ),
        ],
    ) -> Sizing:
        """Call this when the person names a price, to find how much to borrow after the savings
        above the cushion. Returns the loan amount and how the savings divide.
        """
        return Sizing.model_validate(policy.size_loan(goal_price, savings, min_cushion))

    @server.tool()
    def simulate_loan(
        loan: Annotated[Loan, Field(description=_LOAN)],
    ) -> Annotated[CallToolResult, LoanSimulation]:
        """Call this to price a loan the person is considering, made of one or more tracks.
        Returns today's payment, the highest recurring payment and total repaid for the loan and
        per track, each balloon track's balloon due in its last month, each variable track's worst
        historical window and range, and the dates of the market data used. The text is a summary;
        the structured content also holds the month-by-month schedule, for the page.
        """
        market = history_provider()
        try:
            outcomes = [history.simulate(track, market) for track in loan.tracks]
        except history.NoHistoryWindowError as error:
            raise ToolError(str(error)) from error
        monthly = _monthly_totals([outcome.base for outcome in outcomes])
        simulation = LoanSimulation(
            tracks=[TrackSimulation.of(outcome) for outcome in outcomes],
            first_payment=monthly[0],
            max_base_payment=max(monthly),
            total_paid=sum((outcome.base.total_paid for outcome in outcomes), Decimal(0)),
            rate_as_of=market.rate_as_of,
            cpi_as_of=market.cpi_as_of,
        )
        return CallToolResult(
            content=[TextContent(type="text", text=_summary(simulation))],
            structured_content=simulation.model_dump(mode="json"),
        )

    @server.tool()
    def market_series(
        prime_months: Annotated[
            int, Field(ge=1, le=HISTORY_MONTHS, description="How many latest months of prime")
        ],
        cpi_months: Annotated[
            int,
            Field(ge=1, le=HISTORY_MONTHS, description="How many latest months of CPI change"),
        ],
    ) -> MarketSeries:
        """Call this when the person asks about the prime rate or the consumer price index: today's
        prime, how it moved, or how prices rose. Returns today's prime and, oldest first, the prime
        and the CPI's monthly change for the latest months, from the Bank of Israel and the
        Central Bureau of Statistics data the loans are priced with.
        """
        market = history_provider()
        # The aligned months end at the latest published CPI, which trails the daily rate by
        # weeks; the rate's own month closes the prime series, so the chart reaches today.
        prime_window = list(zip(market.months, market.boi_rate, strict=True))
        this_month = market.rate_as_of.replace(day=1)
        if this_month > market.months[-1]:
            prime_window.append((this_month, market.current_boi_rate))
        cpi_window = zip(market.months, market.monthly_inflation, strict=True)
        return MarketSeries(
            current_prime=market.current_boi_rate + PRIME_MARGIN,
            rate_as_of=market.rate_as_of,
            prime=[
                PrimeMonth(month=month, prime=rate + PRIME_MARGIN)
                for month, rate in prime_window[-prime_months:]
            ],
            cpi_as_of=market.cpi_as_of,
            cpi=[
                CpiMonth(
                    month=month,
                    change_percent=(inflation * 100).quantize(_ONE_DECIMAL, ROUND_HALF_UP),
                )
                for month, inflation in list(cpi_window)[-cpi_months:]
            ],
        )

    @server.tool()
    def shortest_comfortable_term(
        principal: Annotated[
            Decimal, Field(ge=MIN_PRINCIPAL, le=MAX_PRINCIPAL, description="Loan amount, ₪")
        ],
        payment_ceiling: Annotated[
            Decimal,
            Field(gt=0, description="assess_affordability's payment_ceiling, ₪ per month"),
        ],
    ) -> ComfortableTerm:
        """Call this to choose the term of the example tracks: the shortest term, in steps of
        6 months, at which suggest_tracks' fixed and prime tracks keep their highest payment, in
        the worst historical window too, within 90% of the payment ceiling. Refused when no term
        up to the longest the simulator prices fits.
        """
        market = history_provider()
        term = policy.shortest_comfortable_term(principal, payment_ceiling, market)
        if term is None:
            raise ToolError(
                f"no term up to {MAX_TERM} months keeps the payment of a {principal} ₪ loan "
                f"within {COMFORT_SHARE:.0%} of a {payment_ceiling} ₪ ceiling; the loan is too "
                "large for this ceiling"
            )
        return ComfortableTerm(term_months=term, payment_limit=payment_ceiling * COMFORT_SHARE)

    @server.tool()
    def shortest_comfortable_offer_term(
        track: Annotated[
            Track,
            Field(
                description="The real offer as one track, with term_months the longest term the "
                "offer allows"
            ),
        ],
        payment_ceiling: Annotated[
            Decimal,
            Field(gt=0, description="assess_affordability's payment_ceiling, ₪ per month"),
        ],
    ) -> OfferTerm:
        """Call this when a real offer lets the person choose the term up to a maximum ("up to 84
        months"): a longer term only adds interest, so the offer is priced at the shortest term,
        in steps of 6 months up to its maximum, that keeps its highest payment, in the worst
        historical window too, within 90% of the payment ceiling. When no term does, returns the
        offer's maximum with comfortable false.
        """
        market = history_provider()
        term = policy.shortest_comfortable_offer_term(track, payment_ceiling, market)
        return OfferTerm(
            term_months=track.term_months if term is None else term,
            comfortable=term is not None,
            payment_limit=payment_ceiling * COMFORT_SHARE,
        )

    @server.tool()
    def suggest_tracks(
        principal: Annotated[
            Decimal, Field(ge=MIN_PRINCIPAL, le=MAX_PRINCIPAL, description="Loan amount, ₪")
        ],
        term_months: Annotated[int, Field(ge=MIN_TERM, le=MAX_TERM, description="Term, months")],
    ) -> TrackSuggestions:
        """Call this when the person has no loan offer yet and needs typical tracks to simulate,
        with the term shortest_comfortable_term gave unless the person asked for another. Returns
        a fixed and a prime track priced from the Bank of Israel's latest average rate on
        household consumer loans, and the month of that rate.
        """
        market = history_provider()
        return TrackSuggestions(
            tracks=policy.suggest_tracks(principal, term_months, market),
            as_of=market.consumer_rate_month,
            source=(
                "Bank of Israel average rate on new unindexed household consumer loans, "
                f"series {CONSUMER_RATE_SERIES}"
            ),
        )
