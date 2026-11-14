"""The agent's own tools for one check: the calls the model makes to save the person's data, to
ask the person a question and to present a recommendation, with the guardrail that keeps a
recommendation within the engine's bounds.

- ToolDeps: the ports, the clock and the id generator the tools act through
- CheckTools: update_profile, set_goal, save_option and present_recommendation, each returning a
  compact key: value summary for the model and emitting an event for the page; update_profile
  returns CHECK_ARCHIVED_RESULT instead when its save archived this check, after which the turn
  ends; ask, emitting the question for the page and returning ASKED_RESULT, after which the turn
  ends; show_chart, emitting a market series from the engine for the page to draw
- ToolError: a refusal whose message tells the model what is wrong and what to do next
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal, cast, get_args

from loan_agent.application.profile_saving import save_profile
from loan_agent.domain.errors import GoalError, ProfileError
from loan_agent.domain.models import Goal, Option, OptionSource, Profile, Recommendation
from loan_agent.ports.engine import Bounds, EngineError, LoanEngine, MarketPoint, Sizing
from loan_agent.ports.events import (
    CHART_SHOWN,
    GOAL_SET,
    OPTION_SAVED,
    PROFILE_UPDATED,
    QUESTION_ASKED,
    RECOMMENDATION_PRESENTED,
    EventSink,
)
from loan_agent.ports.repositories import (
    CheckRepository,
    OptionRepository,
    ProfileRepository,
    RecommendationRepository,
)

_SOURCES: tuple[str, ...] = get_args(OptionSource)

ChartSeries = Literal["prime", "cpi"]
_CHART_SERIES: tuple[str, ...] = get_args(ChartSeries)

ASKED_RESULT = (
    "The question is on the person's screen and this turn ends here; their answer arrives as the "
    "next message."
)

CHECK_ARCHIVED_RESULT = (
    "Saved. The change replaced figures this check's recommendation was computed from, so this "
    "check is archived and this turn ends here; the conversation continues in a new check with "
    "the same goal, which recalculates."
)

# The page's card changes only through a recommendation, so a saved offer it does not reach would
# sit under an older one.
_COMPARE_THE_OFFER = (
    "compare this offer with the saved options and call present_recommendation in this turn; the "
    "person's card changes only through that call"
)


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class ToolDeps:
    profiles: ProfileRepository
    checks: CheckRepository
    options: OptionRepository
    recommendations: RecommendationRepository
    engine: LoanEngine
    sink: EventSink
    clock: Callable[[], datetime]
    new_id: Callable[[], str]


class CheckTools:
    def __init__(self, user_id: str, check_id: str, deps: ToolDeps) -> None:
        self._user_id = user_id
        self._check_id = check_id
        self._deps = deps

    async def update_profile(self, **fields: object) -> str:
        deps = self._deps
        try:
            saved = await save_profile(
                self._user_id, fields, deps.profiles, deps.checks, deps.sink, deps.clock
            )
        except ProfileError as error:
            raise ToolError(f"{error}; correct it and call update_profile again") from None
        profile = saved.profile
        data = {"profile": _json_ready(asdict(profile)), "missing": list(profile.missing())}
        await deps.sink.emit(self._check_id, PROFILE_UPDATED, data)
        if self._check_id in saved.archived:
            return CHECK_ARCHIVED_RESULT
        return summary(profile_figures(profile))

    async def set_goal(self, purpose: str, price: object) -> str:
        if not purpose.strip():
            raise ToolError("purpose is empty; ask the person what the loan is for")
        try:
            goal = Goal(purpose, _amount("price", price))
        except GoalError as error:
            raise ToolError(f"{error}; ask the person for the correct value") from None
        await self._deps.checks.set_goal(self._check_id, goal)
        data = _json_ready(asdict(goal))
        await self._deps.sink.emit(self._check_id, GOAL_SET, data)
        return summary(data)

    async def save_option(
        self,
        loan: Mapping[str, object],
        source: str,
        lender: str | None = None,
        offer_date: str | None = None,
        max_term_months: int | None = None,
    ) -> str:
        if source not in _SOURCES:
            raise ToolError(f"source must be one of {', '.join(_SOURCES)}, not {source!r}")
        if source != "offer" and max_term_months is not None:
            raise ToolError("max_term_months belongs to a real offer; omit it for an example")
        offered = None if offer_date is None else _offer_date(offer_date)
        profile, _ = await self._deps.profiles.get(self._user_id)
        if profile.missing() and (source == "published_average" or max_term_months is not None):
            kept_for = "an example" if source == "published_average" else "a term up to a maximum"
            raise ToolError(
                f"{kept_for} comes only after the whole profile is known; ask the person for: "
                + ", ".join(profile.missing())
            )
        try:
            simulation = await self._deps.engine.simulate(loan)
        except EngineError as error:
            raise ToolError(
                f"The engine refused the loan: {error}; correct the loan and call save_option again"
            ) from None
        # A principal that cannot be read as money is refused at save time, not when a
        # recommendation first sums it.
        _principal(loan)
        if source == "published_average":
            await self._require_within_ceiling(profile, simulation.figures.risk_payment)
        if max_term_months is not None:
            await self._require_offer_term(profile, loan, max_term_months)
        option = Option(
            id=self._deps.new_id(),
            check_id=self._check_id,
            loan=loan,
            source=cast(OptionSource, source),
            lender=lender,
            offer_date=offered,
            summary=simulation.figures,
            created_at=self._deps.clock(),
        )
        await self._deps.options.add(option)
        await self._deps.sink.emit(
            self._check_id,
            OPTION_SAVED,
            {**_option_data(option), "result": simulation.structured},
        )
        saved = {"option_id": option.id, **_whole_shekels(asdict(option.summary))}
        if source == "offer" and not profile.missing():
            return summary({**saved, "next_step": _COMPARE_THE_OFFER})
        return summary(saved)

    async def _require_within_ceiling(self, profile: Profile, risk_payment: Decimal) -> None:
        """An example option is the page's suggestion, so its worst-case payment must fit the
        payment ceiling of the complete profile; a real offer is saved whatever its payment, to
        be compared."""
        bounds = await self._deps.engine.assess(profile.engine_profile())
        if risk_payment > bounds.payment_ceiling:
            raise ToolError(
                f"this example has a worst-case monthly payment of {risk_payment}, above the "
                f"payment_ceiling of {bounds.payment_ceiling}; do not offer it. Save a longer term "
                "or a lower payment that fits the ceiling"
            )

    async def _require_offer_term(
        self, profile: Profile, loan: Mapping[str, object], max_term_months: int
    ) -> None:
        """An offer that leaves the term open is kept at its shortest comfortable term: a longer
        one only adds interest. The simulation already refused a loan of several tracks."""
        tracks = loan["tracks"]
        assert isinstance(tracks, list)
        (track,) = tracks
        bounds = await self._deps.engine.assess(profile.engine_profile())
        try:
            term = await self._deps.engine.offer_term(
                {**track, "term_months": max_term_months}, bounds.payment_ceiling
            )
        except EngineError as error:
            raise ToolError(
                f"The engine refused the offer: {error}; correct it and call save_option again"
            ) from None
        if track["term_months"] != term.term_months:
            raise ToolError(
                f"this offer allows up to {max_term_months} months and the term to save is "
                f"{term.term_months}; save it with term_months {term.term_months}. If the person "
                "chose this term themselves, omit max_term_months"
            )

    async def ask(self, question: Mapping[str, object], lead_in: str | None) -> str:
        if (
            question["offer_clone"]
            and await self._deps.recommendations.latest(self._check_id) is None
        ):
            raise ToolError(
                "offer_clone is for a change to a recommendation this check has; there is none "
                "yet, so do what the person asked in this check"
            )
        field = question["field"]
        profile, _ = await self._deps.profiles.get(self._user_id)
        known = asdict(profile)
        if field in known and known[field] is not None:
            raise ToolError(
                f"{field} is already known: {_summary_value(known[field])}; do not ask for it again"
            )
        if field == "variable_income_minimum" and profile.variable_income == 0:
            raise ToolError("variable_income_minimum is not needed: the variable income is 0")
        await self._deps.sink.emit(
            self._check_id, QUESTION_ASKED, {"question": question, "lead_in": lead_in}
        )
        return ASKED_RESULT

    async def show_chart(self, series: str, months: int) -> str:
        if series not in _CHART_SERIES:
            raise ToolError(f"series must be one of {', '.join(_CHART_SERIES)}, not {series!r}")
        try:
            market = await self._deps.engine.market_series(months)
        except EngineError as error:
            raise ToolError(f"{error}; correct the months and call show_chart again") from None
        points: tuple[MarketPoint, ...]
        if series == "prime":
            points, as_of = market.prime, market.rate_as_of
        else:
            points, as_of = market.cpi_change, market.cpi_as_of
        data = {
            "series": series,
            "as_of": as_of.isoformat(),
            "points": [{"month": p.month.isoformat(), "value": str(p.value)} for p in points],
        }
        await self._deps.sink.emit(self._check_id, CHART_SHOWN, data)
        return (
            f"The {series} chart of {len(points)} months, {points[0].month:%Y-%m} to "
            f"{points[-1].month:%Y-%m}, is on the person's screen under its own title; do not "
            "list its values again"
        )

    async def present_recommendation(
        self, preferred_option_id: str, reasoning: str, alternative_option_id: str | None = None
    ) -> str:
        profile, profile_updated_at = await self._deps.profiles.get(self._user_id)
        check = await self._deps.checks.get(self._user_id, self._check_id)
        missing = [*profile.missing(), *(["goal"] if check.goal is None else [])]
        if missing:
            raise ToolError(
                "A recommendation needs the complete profile and the goal; ask the person for: "
                + ", ".join(missing)
            )
        assert check.goal is not None and profile_updated_at is not None
        assert profile.savings is not None
        if not reasoning.strip():
            raise ToolError("reasoning is empty; explain why the preferred option fits the person")
        named_ids = ["option_id", preferred_option_id, *filter(None, [alternative_option_id])]
        if any(name in reasoning for name in named_ids):
            raise ToolError(
                "reasoning names an option by its id; the person sees it, so name the option by "
                "its track in Hebrew (for example the prime track or the fixed track)"
            )
        if alternative_option_id == preferred_option_id:
            raise ToolError("alternative_option_id must differ from preferred_option_id")
        preferred = await self._option("preferred_option_id", preferred_option_id)
        alternative = (
            None
            if alternative_option_id is None
            else await self._option("alternative_option_id", alternative_option_id)
        )

        bounds = await self._deps.engine.assess(profile.engine_profile())
        sizing = await self._deps.engine.size(check.goal.price, profile.savings, bounds.min_cushion)
        _check_bounds(
            bounds, sizing, [preferred] if alternative is None else [preferred, alternative]
        )
        if preferred.source == "published_average":
            await self._require_no_fitting_offer(bounds, sizing)
        sizing = _as_borrowed(sizing, _principal(preferred.loan))

        recommendation = Recommendation(
            check_id=self._check_id,
            preferred_option_id=preferred.id,
            alternative_option_id=alternative_option_id,
            reasoning=reasoning,
            loan_amount=sizing.loan_amount,
            payment_ceiling=bounds.payment_ceiling,
            min_cushion=bounds.min_cushion,
            cushion_kept=sizing.cushion_kept,
            created_at=self._deps.clock(),
        )
        await self._deps.recommendations.save(recommendation)
        await self._deps.checks.snapshot_profile(self._check_id, at=profile_updated_at)
        await self._deps.sink.emit(
            self._check_id,
            RECOMMENDATION_PRESENTED,
            {
                "bounds": _json_ready(asdict(bounds)),
                "sizing": _json_ready(asdict(sizing)),
                "preferred": _option_data(preferred),
                "alternative": None if alternative is None else _option_data(alternative),
                "reasoning": reasoning,
            },
        )
        return summary(
            {
                "recommendation": "presented",
                "preferred_option_id": preferred.id,
                "alternative_option_id": alternative_option_id,
                "loan_amount": sizing.loan_amount,
                "payment_ceiling": bounds.payment_ceiling,
                "min_cushion": bounds.min_cushion,
                "cushion_kept": sizing.cushion_kept,
            }
        )

    async def _require_no_fitting_offer(self, bounds: Bounds, sizing: Sizing) -> None:
        """An example is an average, not a loan anyone can take, so it never beats a real offer
        that covers the loan within the payment ceiling."""
        for option in await self._deps.options.list(self._check_id):
            if (
                option.source == "offer"
                and _principal(option.loan) >= sizing.loan_amount
                and option.summary.risk_payment <= bounds.payment_ceiling
            ):
                raise ToolError(
                    f"option {option.id} is a real offer within the bounds and the preferred "
                    "option is only an example, which nobody can take; prefer the real offer and "
                    "keep the example as the alternative"
                )

    async def _option(self, argument: str, option_id: str) -> Option:
        try:
            return await self._deps.options.get(self._check_id, option_id)
        except KeyError:
            raise ToolError(
                f"{argument}: this check has no option {option_id!r}; save it with save_option "
                "first and use the option_id it returns"
            ) from None


def _as_borrowed(sizing: Sizing, principal: Decimal) -> Sizing:
    """The loan a recommendation takes may be above the sized one, at the engine's minimum loan or
    at an offer's amount. The savings it spares stay in the cushion."""
    above_sized = principal - sizing.loan_amount
    spared = min(above_sized, sizing.savings_used)
    return replace(
        sizing,
        loan_amount=sizing.loan_amount + above_sized,
        savings_used=sizing.savings_used - spared,
        cushion_kept=sizing.cushion_kept + spared,
    )


def _check_bounds(bounds: Bounds, sizing: Sizing, options: list[Option]) -> None:
    """The guardrail: refuses when no loan is needed, when an option borrows less than the loan
    amount the engine sized (the gap would come out of the minimum cushion), or when an option's
    worst-case recurring payment exceeds the payment ceiling. A balloon is paid once at the end,
    so it is not a recurring payment."""
    if sizing.loan_amount == 0:
        raise ToolError(
            "no loan is needed: the savings cover the price while keeping the minimum cushion of "
            f"{bounds.min_cushion}; tell the person instead of recommending a loan"
        )
    for option in options:
        principal = _principal(option.loan)
        if principal < sizing.loan_amount:
            raise ToolError(
                f"option {option.id} borrows {principal}, below the loan_amount of "
                f"{sizing.loan_amount} the engine sized; the difference would come out of the "
                f"minimum cushion of {bounds.min_cushion}. Save an option with a principal of at "
                f"least {sizing.loan_amount} and recommend that. If {sizing.loan_amount} is above "
                "the engine's maximum loan, no option can cover it: tell the person the purchase "
                "is outside the range this simulator prices, and suggest a larger down payment "
                "or a cheaper goal"
            )
        risk_payment = option.summary.risk_payment
        if risk_payment > bounds.payment_ceiling:
            raise ToolError(
                f"option {option.id} has a worst-case monthly payment of {risk_payment}, above "
                f"the payment_ceiling of {bounds.payment_ceiling}; recommend an option within "
                "the ceiling, or save one with a lower payment (e.g. a longer term or a fixed "
                "rate)"
            )


def _principal(loan: Mapping[str, object]) -> Decimal:
    """The loan's total principal; raises ToolError when a track's principal is neither a string
    nor an integer, since a binary float cannot carry money exactly."""
    tracks = loan["tracks"]
    assert isinstance(tracks, list)
    total = Decimal(0)
    for index, track in enumerate(tracks):
        assert isinstance(track, Mapping)
        value = track["principal"]
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ToolError(
                f'loan.tracks[{index}].principal must be a decimal string such as "80000", '
                f"not {value!r}"
            )
        total += Decimal(value)
    return total


def _amount(name: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise ToolError(f'{name} must be a decimal string such as "55000", not {value!r}')
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ToolError(f"{name} is not a number: {value!r}") from None
    if not amount.is_finite():
        raise ToolError(f"{name} must be a finite number, not {value!r}")
    return amount


def _offer_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(
            f"offer_date must be an ISO date such as 2026-10-20, not {value!r}"
        ) from None


def _option_data(option: Option) -> dict[str, object]:
    return {
        "option_id": option.id,
        "loan": option.loan,
        "source": option.source,
        "lender": option.lender,
        "offer_date": _json_value(option.offer_date),
        "figures": option.summary.to_json(),
    }


def _whole_shekels(figures: Mapping[str, object]) -> dict[str, object]:
    """The figures with every amount rounded to the shekel, as the person reads them; the
    figures' amounts are all money."""
    return {
        key: value.quantize(Decimal(1), ROUND_HALF_UP) if isinstance(value, Decimal) else value
        for key, value in figures.items()
    }


def _json_ready(values: Mapping[str, object]) -> dict[str, object]:
    return {key: _json_value(value) for key, value in values.items()}


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return value


def summary(values: Mapping[str, object]) -> str:
    return "\n".join(f"{key}: {_summary_value(value)}" for key, value in values.items())


def profile_figures(profile: Profile) -> dict[str, object]:
    missing = profile.missing()
    figures: dict[str, object] = {}
    for name, value in asdict(profile).items():
        if value is not None:
            figures[name] = value
        elif name in missing:
            figures[name] = "not told"
        else:
            figures[name] = "not needed"
    figures["missing"] = ", ".join(missing) if missing else "none"
    return figures


def _summary_value(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(_json_value(value))
