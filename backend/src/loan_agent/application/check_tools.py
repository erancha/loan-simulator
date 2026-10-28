"""The agent's own tools for one check: the calls the model makes to save the person's data and to
present a recommendation, with the guardrail that keeps a recommendation within the engine's
bounds.

- ToolDeps: the ports, the clock and the id generator the tools act through
- CheckTools: update_profile, set_goal, save_option and present_recommendation, each returning a
  compact key: value summary for the model and emitting an event for the page
- ToolError: a refusal whose message tells the model what is wrong and what to do next
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast, get_args

from loan_agent.domain.errors import GoalError, ProfileError
from loan_agent.domain.models import Goal, Option, OptionSource, Recommendation
from loan_agent.ports.engine import Bounds, EngineError, LoanEngine, Sizing
from loan_agent.ports.events import (
    GOAL_SET,
    OPTION_SAVED,
    PROFILE_UPDATED,
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
        profile, _ = await self._deps.profiles.get(self._user_id)
        try:
            profile = profile.merged(fields)
        except ProfileError as error:
            raise ToolError(f"{error}; correct it and call update_profile again") from None
        await self._deps.profiles.save(self._user_id, profile)
        data = {"profile": _json_ready(asdict(profile)), "missing": list(profile.missing())}
        await self._deps.sink.emit(self._check_id, PROFILE_UPDATED, data)
        told = {
            name: "not told" if value is None else value for name, value in asdict(profile).items()
        }
        return _summary({**told, "missing": ", ".join(profile.missing()) or "none"})

    async def set_goal(self, purpose: str, price: object, trade_in_value: object) -> str:
        if not purpose.strip():
            raise ToolError("purpose is empty; ask the person what the loan is for")
        try:
            goal = Goal(purpose, _amount("price", price), _amount("trade_in_value", trade_in_value))
        except GoalError as error:
            raise ToolError(f"{error}; ask the person for the correct value") from None
        await self._deps.checks.set_goal(self._check_id, goal)
        data = _json_ready(asdict(goal))
        await self._deps.sink.emit(self._check_id, GOAL_SET, data)
        return _summary(data)

    async def save_option(
        self,
        loan: Mapping[str, object],
        source: str,
        lender: str | None = None,
        offer_date: str | None = None,
    ) -> str:
        if source not in _SOURCES:
            raise ToolError(f"source must be one of {', '.join(_SOURCES)}, not {source!r}")
        offered = None if offer_date is None else _offer_date(offer_date)
        try:
            simulation = await self._deps.engine.simulate(loan)
        except EngineError as error:
            raise ToolError(
                f"The engine refused the loan: {error}; correct the loan and call save_option again"
            ) from None
        # A principal that cannot be read as money is refused at save time, not when a
        # recommendation first sums it.
        _principal(loan)
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
        return _summary({"option_id": option.id, **asdict(option.summary)})

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
        if alternative_option_id == preferred_option_id:
            raise ToolError("alternative_option_id must differ from preferred_option_id")
        preferred = await self._option("preferred_option_id", preferred_option_id)
        alternative = (
            None
            if alternative_option_id is None
            else await self._option("alternative_option_id", alternative_option_id)
        )

        bounds = await self._deps.engine.assess(profile.engine_profile())
        sizing = await self._deps.engine.size(
            check.goal.price, check.goal.trade_in_value, profile.savings, bounds.min_cushion
        )
        _check_bounds(
            bounds, sizing, [preferred] if alternative is None else [preferred, alternative]
        )

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
        return _summary(
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

    async def _option(self, argument: str, option_id: str) -> Option:
        try:
            return await self._deps.options.get(self._check_id, option_id)
        except KeyError:
            raise ToolError(
                f"{argument}: this check has no option {option_id!r}; save it with save_option "
                "first and use the option_id it returns"
            ) from None


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


def _summary(values: Mapping[str, object]) -> str:
    return "\n".join(f"{key}: {_summary_value(value)}" for key, value in values.items())


def _summary_value(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(_json_value(value))
