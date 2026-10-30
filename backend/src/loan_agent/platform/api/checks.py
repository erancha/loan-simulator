"""Check routes: create, list, read and delete a person's checks, and send a message that starts
a turn.

Core building blocks:
- router: POST/GET /api/checks, GET/DELETE /api/checks/{id}, POST /api/checks/{id}/messages
- register_error_handlers: another person's check answers 404 like an unknown one; a message or a
  delete while a turn runs answers 409; a message over the cap answers 429 with Retry-After
"""

import math
from datetime import datetime

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse

from loan_agent.domain.errors import CheckNotFoundError, TurnConflictError, TurnLimitError
from loan_agent.domain.models import Check
from loan_agent.domain.models import Recommendation as DomainRecommendation
from loan_agent.platform.api.auth import CurrentUser
from loan_agent.platform.api.schemas import (
    CheckSummary,
    CheckView,
    CreatedCheck,
    Message,
    OptionView,
    Recommendation,
)
from loan_agent.platform.dependencies import AppDeps, Deps, Runner, get_deps

router = APIRouter(prefix="/api/checks")


async def _recommends_examples_only(
    deps: AppDeps, recommendation: DomainRecommendation | None
) -> bool:
    if recommendation is None:
        return False
    named = [recommendation.preferred_option_id]
    if recommendation.alternative_option_id is not None:
        named.append(recommendation.alternative_option_id)
    for option_id in named:
        option = await deps.options.get(recommendation.check_id, option_id)
        if option.source != "published_average":
            return False
    return True


async def _summary(
    deps: AppDeps, check: Check, profile_updated_at: datetime | None
) -> CheckSummary:
    recommendation = await deps.recommendations.latest(check.id)
    return CheckSummary.of(
        check,
        recommendation,
        await _recommends_examples_only(deps, recommendation),
        check.is_stale(profile_updated_at),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_check(user: CurrentUser, runner: Runner) -> CreatedCheck:
    check = await runner.create(user)
    return CreatedCheck(id=check.id)


@router.get("")
async def list_checks(user: CurrentUser, deps: Deps) -> list[CheckSummary]:
    """Newest first."""
    _, profile_updated_at = await deps.profiles.get(user.id)
    return [
        await _summary(deps, check, profile_updated_at) for check in await deps.checks.list(user.id)
    ]


@router.get("/{check_id}")
async def get_check(check_id: str, user: CurrentUser, deps: Deps) -> CheckView:
    check = await deps.checks.get(user.id, check_id)
    _, profile_updated_at = await deps.profiles.get(user.id)
    recommendation = await deps.recommendations.latest(check.id)
    return CheckView(
        id=check.id,
        created_at=check.created_at,
        goal=check.goal,
        options=[OptionView.of(option) for option in await deps.options.list(check.id)],
        recommendation=None if recommendation is None else Recommendation.of(recommendation),
        profile_stale=check.is_stale(profile_updated_at),
    )


@router.delete("/{check_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_check(check_id: str, user: CurrentUser, runner: Runner) -> None:
    await runner.delete(user, check_id)


@router.post("/{check_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(check_id: str, body: Message, user: CurrentUser, runner: Runner) -> None:
    """Accepted once the message is stored; the reply arrives on the check's event stream."""
    await runner.send(user, check_id, body.text)


def register_error_handlers(app: FastAPI) -> None:
    async def not_found(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, CheckNotFoundError)
        return JSONResponse({"detail": "no such check"}, status_code=status.HTTP_404_NOT_FOUND)

    async def conflict(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, TurnConflictError)
        return JSONResponse(
            {"detail": str(error), "check_id": error.check_id},
            status_code=status.HTTP_409_CONFLICT,
        )

    async def over_limit(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, TurnLimitError)
        wait = error.next_allowed - get_deps(request).clock()
        return JSONResponse(
            {"detail": str(error), "next_allowed": error.next_allowed.isoformat()},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(math.ceil(wait.total_seconds()))},
        )

    app.add_exception_handler(CheckNotFoundError, not_found)
    app.add_exception_handler(TurnConflictError, conflict)
    app.add_exception_handler(TurnLimitError, over_limit)
