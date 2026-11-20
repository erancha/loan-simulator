"""The loan-engine tools, described for a language model, with money rounded to agorot
(hundredths of a shekel).

- Output models: Bounds, LoanSimulation (TrackSimulation, MonthRow), ScenarioSimulation
  (PricedScenario, ScenarioTrack), ComfortableTerm, OfferTerm, ProposedTerm, LargestLoan,
  TrackSuggestions, MarketSeries (PrimeMonth, CpiMonth), OfferReadings (Reading)
- register_tools(): adds the tools to a server; each reads market data from history_provider

simulate_loan returns its LoanSimulation as structured content and only a short summary as text,
so the agent will be able to pass the schedule to the page without it filling the model's context.

Argument validation failures, the domain's NoHistoryWindowError and an offer with neither a
number nor a payment reach the caller as tool errors whose message names the field or the term at
fault; the MCP SDK withholds the text of any other exception.
"""

from collections.abc import Callable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from loan_engine.domain import affordability, history, policy, readings, schedule
from loan_engine.domain.assumptions import (
    HISTORY_MONTHS,
    PRIME_MARGIN,
    SIMILAR_RATE_POINTS,
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
from loan_engine.domain.models import DEFAULT_SCENARIO, Loan, Profile, Scenario, Track
from loan_engine.market.boi import CONSUMER_RATE_SERIES

_AGOROT = Decimal("0.01")


def _to_agorot(value: Decimal) -> Decimal:
    return value.quantize(_AGOROT, rounding=ROUND_HALF_UP)


Money = Annotated[Decimal, AfterValidator(_to_agorot)]

_BASE_PATH = (
    f"the base path: today's rates held flat and, for CPI-linked tracks, "
    f"{DEFAULT_SCENARIO.cpi_per_year}% annual inflation"
)

_SCENARIO = (
    "The future to price the loan on, held for the whole loan: cpi_per_year, how much the CPI "
    "rises each year in percent (5 means 5%), and prime_per_year, how much prime rises each year "
    "in percentage points. For a movement the person describes as in recent years, give "
    "cpi_like_last_years or prime_like_last_years, the number of years, in its place. Omit a "
    "movement the person did not name: it keeps today's assumption, "
    f"{DEFAULT_SCENARIO.cpi_per_year}% and {DEFAULT_SCENARIO.prime_per_year}."
)

_PROFILE = (
    "The person's monthly finances, every amount in ₪ per month: net_fixed_income (income after "
    "tax, including the variable income that arrives even in a weak month) and fixed_expenses "
    "(rent, bills, other recurring spending and payments on existing loans)."
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
    counted_income: Money = Field(description="Monthly income the ceiling is based on, ₪ per month")
    income_share: Decimal = Field(description="Fraction of the income one loan payment may take")
    ceiling_by_income_share: Money = Field(
        description="The cap that is income_share of the income, ₪ per month"
    )
    disposable_share: Decimal = Field(
        description="Fraction of the income left after fixed expenses a payment may take"
    )
    ceiling_by_disposable_income: Money = Field(
        description="The cap that is disposable_share of the income minus the fixed expenses, "
        "₪ per month; negative when the expenses exceed the income"
    )
    reasons: list[affordability.Reason] = Field(description="How the ceiling was set, in order")


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


_CONSUMER_RATE = (
    "the Bank of Israel average annual percent on new unindexed household consumer loans"
)


class TrackSimulation(_Output):
    rate_today: Decimal = Field(
        description="Annual percent the track charges in month 1: the fixed rate, or today's "
        "prime plus the spread; for a CPI-linked track, the rate on top of the CPI"
    )
    against_consumer_rate: policy.RateAgainstMarket | None = Field(
        description=f"rate_today against {_CONSUMER_RATE} (the loan's consumer_rate), "
        f"similar within {SIMILAR_RATE_POINTS} percentage points; null for a CPI-linked track, "
        "whose rate is not comparable with an unlinked one"
    )
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
    def of(
        cls, track: Track, outcome: history.TrackOutcome, market: history.MarketHistory
    ) -> "TrackSimulation":
        return cls(
            rate_today=history.rate_today(track, market),
            against_consumer_rate=policy.rate_against_market(track, market),
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
    consumer_rate: Decimal = Field(
        description=f"{_CONSUMER_RATE[0].upper()}{_CONSUMER_RATE[1:]}, the rate suggest_tracks "
        "prices its fixed track at"
    )
    consumer_rate_month: date = Field(description="Month of consumer_rate")


class ScenarioTrack(_Output):
    first_payment: Money = Field(description="Payment in month 1 on the scenario, ₪")
    max_payment: Money = Field(
        description="Highest recurring monthly payment on the scenario, without the balloon, ₪"
    )
    balloon_due: Money | None = Field(description=f"{_BALLOON_DUE}; on the scenario")
    total_paid: Money = Field(
        description="Total repaid on the scenario, including fees and the balloon, ₪"
    )

    @classmethod
    def of(cls, priced: schedule.Schedule) -> "ScenarioTrack":
        return cls(
            first_payment=priced.first_payment,
            max_payment=priced.max_payment,
            balloon_due=priced.balloon_due,
            total_paid=priced.total_paid,
        )


class PricedScenario(_Output):
    """The scenario as priced: every movement as its yearly figure, and the years it was taken
    from when the person described it as the last years."""

    cpi_per_year: Decimal = Field(description="The CPI's yearly rise priced, percent")
    prime_per_year: Decimal = Field(description="Prime's yearly rise priced, percentage points")
    cpi_like_last_years: int | None = Field(description="The years cpi_per_year averages, if any")
    prime_like_last_years: int | None = Field(
        description="The years prime_per_year averages, if any"
    )


class ScenarioSimulation(_Output):
    scenario: PricedScenario = Field(description="The scenario priced, with its defaults filled in")
    tracks: list[ScenarioTrack] = Field(description="One result per track, in input order")
    first_payment: Money = Field(description="Today's monthly payment of the whole loan, ₪")
    max_payment: Money = Field(
        description="Highest recurring monthly payment of the whole loan on the scenario, "
        "without the tracks' balloons, ₪"
    )
    total_paid: Money = Field(description="Total repaid for the whole loan on the scenario, ₪")
    rate_as_of: date = Field(description="Date of the Bank of Israel rate the scenario starts at")


class ComfortableTerm(_Output):
    term_months: int | None = Field(
        description="The shortest comfortable term, months; null when no term up to the longest "
        "the simulator prices fits"
    )


class OfferTerm(_Output):
    term_months: int = Field(
        description="The term to price the offer at: the shortest comfortable term, or the "
        "offer's longest term when none is comfortable"
    )
    comfortable: bool = Field(description="Whether term_months keeps the payment within the limit")


class ProposedTerm(_Output):
    term_months: int = Field(description="The shortest term whose first payment is under the limit")
    first_payment: Money = Field(
        description="The higher first payment of the two unlinked tracks at that term on "
        f"{_BASE_PATH}, ₪"
    )


class LargestLoan(_Output):
    loan_amount: Money | None = Field(
        description="The largest loan on which at least one track fits the ceiling at the term, "
        "₪; null when even the smallest loan does not fit"
    )


class TrackSuggestions(_Output):
    tracks: list[Track] = Field(
        description="A fixed track and a prime track, both unlinked, then a pension fund's fixed "
        "track linked to the CPI"
    )
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
    consumer_rate: Decimal = Field(
        description="The Bank of Israel's latest average rate on new household consumer loans, "
        "annual percent"
    )
    consumer_rate_month: date = Field(description="Month of consumer_rate")


class Reading(_Output):
    kind: readings.ReadingKind
    track: Track = Field(description="The offer as one spitzer track under this reading")
    first_payment: Money = Field(description=f"Payment in month 1 on {_BASE_PATH}, ₪")
    total_rate: Decimal = Field(description="Annual percent the reading charges today")
    approximate: bool = Field(
        description="True for a linked reading priced at the rate of an unlinked payment"
    )


class OfferReadings(_Output):
    prime: Decimal = Field(description="Today's prime, annual percent")
    rate_as_of: date = Field(description="Date of the Bank of Israel rate used")
    payment_rate: Decimal | None = Field(
        description="Annual percent at which a fixed unlinked track starts with the quoted "
        "payment; null without a payment or when no priced rate gives it"
    )
    readings: list[Reading] = Field(
        description="The loans the offer may mean, each within the priced ranges"
    )


_ONE_DECIMAL = Decimal("0.1")


def _summary(loan: LoanSimulation) -> str:
    lines = [f"Figures are on {_BASE_PATH}, except in a named historical window."]
    lines += [
        _track_summary(number, track, loan) for number, track in enumerate(loan.tracks, start=1)
    ]
    lines.append(
        f"Loan: first payment {loan.first_payment} ₪; peak recurring payment "
        f"{loan.max_base_payment} ₪; total repaid {loan.total_paid} ₪."
    )
    lines.append(
        f"Market data: Bank of Israel rate as of {loan.rate_as_of}, CPI as of "
        f"{loan.cpi_as_of:%Y-%m}. The month-by-month schedule is in the structured content."
    )
    return "\n".join(lines)


def _track_summary(number: int, track: TrackSimulation, loan: LoanSimulation) -> str:
    parts = [
        _rate_summary(track, loan),
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
        assert track.total_paid_range is not None and track.max_payment_range is not None
        totals, peaks = track.total_paid_range, track.max_payment_range
        parts.append(
            f"total repaid across the historical windows {totals.low} to {totals.high} ₪, "
            f"peak recurring payment across them {peaks.low} to {peaks.high} ₪"
        )
    return f"Track {number}: " + "; ".join(parts) + "."


def _rate_summary(track: TrackSimulation, loan: LoanSimulation) -> str:
    if track.against_consumer_rate is None:
        return f"rate today {track.rate_today}% on top of the CPI"
    against = {"above": "above", "similar": "similar to", "below": "below"}
    return (
        f"rate today {track.rate_today}%, {against[track.against_consumer_rate]} the average "
        f"consumer loan rate of {loan.consumer_rate}% as of {loan.consumer_rate_month:%Y-%m}"
    )


def _range(bounds: tuple[Decimal, Decimal] | None) -> MoneyRange | None:
    return None if bounds is None else MoneyRange(low=bounds[0], high=bounds[1])


def _proposed(tracks: Sequence[Track], term: int, market: history.MarketHistory) -> ProposedTerm:
    first = max(history.simulate(track, market).base.first_payment for track in tracks)
    return ProposedTerm(term_months=term, first_payment=first)


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
        the income counted, the two caps it is the lower of, each with its share, and reason
        codes for how the payment was set.
        """
        return Bounds.model_validate(affordability.assess_affordability(profile))

    @server.tool()
    def simulate_loan(
        loan: Annotated[Loan, Field(description=_LOAN)],
    ) -> Annotated[CallToolResult, LoanSimulation]:
        """Call this to price a loan the person is considering, made of one or more tracks.
        Returns today's payment, the highest recurring payment and total repaid for the loan and
        per track, each track's rate today and, unlinked, how it stands against the average rate
        on consumer loans, each balloon track's balloon due in its last month, each variable
        track's worst historical window and range, and the dates of the market data used. The
        text is a summary; the structured content also holds the month-by-month schedule, for
        the page.
        """
        market = history_provider()
        try:
            outcomes = [history.simulate(track, market) for track in loan.tracks]
        except history.NoHistoryWindowError as error:
            raise ToolError(str(error)) from error
        monthly = _monthly_totals([outcome.base for outcome in outcomes])
        simulation = LoanSimulation(
            tracks=[
                TrackSimulation.of(track, outcome, market)
                for track, outcome in zip(loan.tracks, outcomes, strict=True)
            ],
            first_payment=monthly[0],
            max_base_payment=max(monthly),
            total_paid=sum((outcome.base.total_paid for outcome in outcomes), Decimal(0)),
            rate_as_of=market.rate_as_of,
            cpi_as_of=market.cpi_as_of,
            consumer_rate=market.consumer_rate,
            consumer_rate_month=market.consumer_rate_month,
        )
        return CallToolResult(
            content=[TextContent(type="text", text=_summary(simulation))],
            structured_content=simulation.model_dump(mode="json"),
        )

    @server.tool()
    def simulate_scenario(
        loan: Annotated[Loan, Field(description=_LOAN)],
        scenario: Annotated[Scenario, Field(description=_SCENARIO)],
    ) -> Annotated[CallToolResult, ScenarioSimulation]:
        """Call this to price a loan on a future the person names: the CPI rising cpi_per_year
        percent a year and prime rising prime_per_year points a year, for the whole loan. Returns
        today's payment, the highest recurring payment and the total repaid, for the loan and per
        track. It replays no historical window; simulate_loan gives those.
        """
        market = history_provider()
        try:
            scenario = history.resolved(scenario, market)
        except history.NoHistoryWindowError as error:
            raise ToolError(str(error)) from error
        priced = [history.price(track, market, scenario) for track in loan.tracks]
        monthly = _monthly_totals(priced)
        simulation = ScenarioSimulation(
            scenario=PricedScenario.model_validate(scenario.model_dump()),
            tracks=[ScenarioTrack.of(one) for one in priced],
            first_payment=monthly[0],
            max_payment=max(monthly),
            total_paid=sum((one.total_paid for one in priced), Decimal(0)),
            rate_as_of=market.rate_as_of,
        )
        text = (
            f"On the scenario of the CPI rising {scenario.cpi_per_year}% a year and prime "
            f"{scenario.prime_per_year} points a year from {market.rate_as_of}: first payment "
            f"{simulation.first_payment} ₪; peak recurring payment {simulation.max_payment} ₪; "
            f"total repaid {simulation.total_paid} ₪."
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
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
        Central Bureau of Statistics data the loans are priced with, and the Bank of Israel's
        latest average rate on new consumer loans.
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
            consumer_rate=market.consumer_rate,
            consumer_rate_month=market.consumer_rate_month,
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
        any_track: Annotated[
            bool,
            Field(description="True to fit when at least one track does, not every track"),
        ] = False,
    ) -> ComfortableTerm:
        """Call this to choose the term of the example tracks: the shortest term, in steps of
        6 months, at which suggest_tracks' unlinked fixed and prime tracks keep their highest
        payment, in the worst historical window too, within the payment ceiling, or with
        any_track at least one of them; the pension fund track is left out, as few lenders offer
        it. term_months is null when no term up to the longest the simulator prices fits.
        """
        market = history_provider()
        term = policy.shortest_comfortable_term(
            principal, payment_ceiling, market, any_track=any_track
        )
        return ComfortableTerm(term_months=term)

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
        historical window too, within the payment ceiling. When no term does, returns the
        offer's maximum with comfortable false.
        """
        market = history_provider()
        term = policy.shortest_comfortable_offer_term(track, payment_ceiling, market)
        return OfferTerm(
            term_months=track.term_months if term is None else term,
            comfortable=term is not None,
        )

    @server.tool()
    def propose_term(
        principal: Annotated[
            Decimal, Field(ge=MIN_PRINCIPAL, le=MAX_PRINCIPAL, description="Loan amount, ₪")
        ],
        payment_limit: Annotated[
            Decimal, Field(gt=0, description="The first payment must be below this, ₪ per month")
        ],
    ) -> ProposedTerm:
        """Call this to choose the term of the example tracks from the first payment the person
        wants to stay under: the shortest term, in steps of 6 months, at which suggest_tracks'
        unlinked fixed and prime tracks both start below the limit, or the longest the simulator
        prices when none does. Returns that term and the higher first payment of the two.
        """
        market = history_provider()
        term = policy.proposed_term(principal, payment_limit, market)
        return _proposed(policy.lender_tracks(principal, term, market), term, market)

    @server.tool()
    def propose_offer_term(
        track: Annotated[
            Track,
            Field(
                description="The real offer as one track, with term_months the longest term the "
                "offer allows"
            ),
        ],
        payment_limit: Annotated[
            Decimal, Field(gt=0, description="The first payment must be below this, ₪ per month")
        ],
    ) -> ProposedTerm:
        """Call this when a real offer lets the person choose the term up to a maximum and wants
        to stay under a first payment: the shortest term, in steps of 6 months up to the
        offer's maximum, at which the offer's first payment is below the limit, or the offer's
        maximum when none is. Returns that term and the first payment at it.
        """
        market = history_provider()
        term = policy.proposed_offer_term(track, payment_limit, market)
        return _proposed([track.model_copy(update={"term_months": term})], term, market)

    @server.tool()
    def largest_comfortable_loan(
        payment_ceiling: Annotated[
            Decimal,
            Field(gt=0, description="assess_affordability's payment_ceiling, ₪ per month"),
        ],
        term_months: Annotated[int, Field(ge=MIN_TERM, le=MAX_TERM, description="Term, months")],
    ) -> LargestLoan:
        """Call this to tell the person the largest loan their payment ceiling carries at a term:
        the largest amount for which suggest_tracks' unlinked fixed or prime track keeps its
        highest payment, in the worst historical window too, within the ceiling. loan_amount is null
        when even the smallest loan the simulator prices does not fit.
        """
        loan = policy.largest_comfortable_loan(payment_ceiling, term_months, history_provider())
        return LargestLoan(loan_amount=loan)

    @server.tool()
    def offer_readings(
        principal: Annotated[
            Decimal, Field(ge=MIN_PRINCIPAL, le=MAX_PRINCIPAL, description="Loan amount, ₪")
        ],
        term_months: Annotated[int, Field(ge=MIN_TERM, le=MAX_TERM, description="Term, months")],
        stated_rate: Annotated[
            Decimal | None,
            Field(
                ge=MIN_PRIME_SPREAD,
                le=MAX_ANNUAL_RATE,
                description="The annual percent the offer states, whatever it is of",
            ),
        ] = None,
        monthly_payment: Annotated[
            Decimal | None, Field(gt=0, description="The monthly payment the offer quotes, ₪")
        ] = None,
        prime_total: Annotated[
            bool,
            Field(description="True to also read stated_rate as prime's total rate today"),
        ] = False,
    ) -> OfferReadings:
        """Call this to read a lender's offer whose type its words leave open. With stated_rate X
        returns prime + X, optionally prime totalling X today, fixed X and fixed X linked; with
        only monthly_payment, the fixed rate that gives the payment read as fixed, as prime and
        as linked. Each reading is one spitzer track with its first payment.
        """
        market = history_provider()
        try:
            offer = readings.offer_readings(
                principal, term_months, stated_rate, monthly_payment, prime_total, market
            )
        except (readings.NoOfferFigureError, history.NoHistoryWindowError) as error:
            raise ToolError(str(error)) from error
        return OfferReadings(
            prime=offer.prime,
            rate_as_of=market.rate_as_of,
            payment_rate=offer.payment_rate,
            readings=[Reading.model_validate(reading) for reading in offer.readings],
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
        household consumer loans, and the month of that rate, then the fixed track linked to the
        CPI that a pension, provident or study fund lends its members at.
        """
        market = history_provider()
        return TrackSuggestions(
            tracks=policy.suggest_tracks(principal, term_months, market),
            as_of=market.consumer_rate_month,
            source=(
                "Bank of Israel average rate on new unindexed household consumer loans, "
                f"series {CONSUMER_RATE_SERIES}; the linked track at the upper end of the rate a "
                "large pension fund publishes for loans to its members"
            ),
        )
