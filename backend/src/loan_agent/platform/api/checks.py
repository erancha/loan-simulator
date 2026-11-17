"""Check routes: create, list, read, clone and delete a person's checks, save the figures of a
check's panel, and send a message that starts a turn.

Core building blocks:
- router: POST/GET /api/checks, GET/DELETE /api/checks/{id}, POST /api/checks/{id}/clone,
  /archive and /restore, POST /api/checks/{id}/messages, /market-sample, /offer-sample,
  /term-ceiling, /opening, /term-confirmation and /offer-skip, PUT /api/checks/{id}/finances and
  /term, PUT /api/checks/{id}/awaiting-offers/{awaiting_id} and its /amount
- register_error_handlers: another person's check answers 404 like an unknown one, as does an
  awaiting offer the check does not hold; a message, a clone, an archive, a delete, a finances
  save, a term save, a reading or an amount answer while a turn runs answers 409, as do a
  message, a finances save, a term save, a reading or an amount answer to an archived check, a
  second archive, and a restore of a check that is open; figures, a term, a reading, an amount
  answer or an opening's loan that cannot be saved answer 422 with the reason; a message over the
  cap answers 429 with Retry-After
"""

import math

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse

from loan_agent.application.check_tools import ToolError
from loan_agent.domain.errors import (
    AwaitingOfferNotFoundError,
    CheckArchivedError,
    CheckNotFoundError,
    CheckNotRestorableError,
    FinancesError,
    TurnConflictError,
    TurnLimitError,
)
from loan_agent.domain.models import Check, compares_options
from loan_agent.domain.models import Recommendation as DomainRecommendation
from loan_agent.platform.api.auth import CurrentUser
from loan_agent.platform.api.schemas import (
    AmountAnswer,
    CheckSummary,
    CheckView,
    CreatedCheck,
    FinancesUpdate,
    Message,
    Opening,
    ReadingConfirmation,
    TermCeiling,
    TermConfirmation,
)
from loan_agent.platform.dependencies import AppDeps, Deps, Runner, get_deps
from loan_agent.ports.engine import EngineError
from loan_agent.ports.events import MESSAGE_USER

router = APIRouter(prefix="/api/checks")


async def _recommends_examples_only(
    deps: AppDeps, recommendation: DomainRecommendation | None
) -> bool:
    if recommendation is None:
        return False
    for option_id in recommendation.named_option_ids:
        option = await deps.options.get(recommendation.check_id, option_id)
        if option.source != "example":
            return False
    return True


async def _summary(deps: AppDeps, check: Check, started: bool) -> CheckSummary:
    recommendation = await deps.recommendations.latest(check.id)
    return CheckSummary.of(
        check,
        recommendation,
        await _recommends_examples_only(deps, recommendation),
        recommendation is not None
        and compares_options(
            await deps.options.list(check.id),
            recommendation.named_option_ids,
            check.term_months,
        ),
        started,
        await deps.awaiting.list(check.id),
    )


async def _view(deps: AppDeps, check: Check) -> CheckView:
    return CheckView.of(
        check, await deps.options.list(check.id), await deps.recommendations.latest(check.id)
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_check(user: CurrentUser, runner: Runner) -> CreatedCheck:
    check = await runner.create(user)
    return CreatedCheck(id=check.id)


@router.get("")
async def list_checks(user: CurrentUser, deps: Deps) -> list[CheckSummary]:
    """Newest first."""
    started = set(await deps.events.checks_with(user.id, MESSAGE_USER))
    return [
        await _summary(deps, check, check.id in started)
        for check in await deps.checks.list(user.id)
    ]


@router.get("/{check_id}")
async def get_check(check_id: str, user: CurrentUser, deps: Deps) -> CheckView:
    return await _view(deps, await deps.checks.get(user.id, check_id))


@router.post("/{check_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_check(check_id: str, user: CurrentUser, runner: Runner) -> CreatedCheck:
    clone = await runner.clone(user, check_id)
    return CreatedCheck(id=clone.id)


@router.post("/{check_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_check(check_id: str, user: CurrentUser, runner: Runner) -> None:
    await runner.archive(user, check_id)


@router.post("/{check_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_check(check_id: str, user: CurrentUser, runner: Runner) -> None:
    await runner.restore(user, check_id)


@router.put("/{check_id}/finances")
async def save_check_finances(
    check_id: str, body: FinancesUpdate, user: CurrentUser, runner: Runner, deps: Deps
) -> CheckView:
    """Saves through the same path as the model's tool, so the ceiling derived from complete
    figures is stored with them."""
    return await _view(deps, await runner.save_finances(user, check_id, body.sent()))


@router.post("/{check_id}/term-ceiling", status_code=status.HTTP_202_ACCEPTED)
async def send_term_ceiling(
    check_id: str, body: TermCeiling, user: CurrentUser, runner: Runner
) -> None:
    """A ceiling typed on the term card: saved as stated, and a term card for it follows on the
    event stream, with no model call; the errors are a message's."""
    await runner.send_term_ceiling(user, check_id, body.text, body.payment_ceiling)


@router.put("/{check_id}/term", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_term(
    check_id: str, body: TermConfirmation, user: CurrentUser, runner: Runner
) -> None:
    """The term the person confirms on the term card, and a ceiling typed beside it, saved before
    the line that tells the model, so the model reads them as set rather than judging the line."""
    await runner.save_term(user, check_id, body.term_months, body.payment_ceiling)


@router.put("/{check_id}/awaiting-offers/{awaiting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_reading(
    check_id: str, awaiting_id: str, body: ReadingConfirmation, user: CurrentUser, runner: Runner
) -> None:
    """The reading the person confirms on an awaiting offer's card, saved as their offer before
    the line that tells the model, so the recommendation updates on a saved offer."""
    await runner.confirm_reading(user, check_id, awaiting_id, body.reading)


@router.put(
    "/{check_id}/awaiting-offers/{awaiting_id}/amount", status_code=status.HTTP_204_NO_CONTENT
)
async def answer_amount(
    check_id: str, awaiting_id: str, body: AmountAnswer, user: CurrentUser, runner: Runner
) -> None:
    """The lender's answer to an offer quoted for less than the check's loan, given on its card:
    the offer saved at the loan amount, or dropped, before the line that tells the model."""
    await runner.answer_amount(user, check_id, awaiting_id, body.covers, body.reading)


@router.delete("/{check_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_check(check_id: str, user: CurrentUser, runner: Runner) -> None:
    await runner.delete(user, check_id)


@router.post("/{check_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(check_id: str, body: Message, user: CurrentUser, runner: Runner) -> None:
    """Accepted once the message is stored; the reply arrives on the check's event stream."""
    await runner.send(user, check_id, body.text)


@router.post("/{check_id}/offer-sample", status_code=status.HTTP_202_ACCEPTED)
async def send_offer_sample(
    check_id: str, body: Message, user: CurrentUser, runner: Runner
) -> None:
    """The page's offer chip, answered with the offer form and no model call; the form arrives on
    the event stream as a question does, and the errors are a message's."""
    await runner.send_offer_sample(user, check_id, body.text)


@router.post("/{check_id}/market-sample", status_code=status.HTTP_202_ACCEPTED)
async def send_market_sample(
    check_id: str, body: Message, user: CurrentUser, runner: Runner
) -> None:
    """The page's market-data sample, answered from the market data with no model call; the
    answer arrives on the event stream as a reply does, and the errors are a message's."""
    await runner.send_market_sample(user, check_id, body.text)


@router.post("/{check_id}/opening", status_code=status.HTTP_202_ACCEPTED)
async def send_opening(check_id: str, body: Opening, user: CurrentUser, runner: Runner) -> None:
    """The opening card's goal and amount, saved as the check's loan before the line is stored;
    the term card follows on the event stream with no model call. The errors are a message's,
    and 422 with the reason for a loan that cannot be saved."""
    await runner.send_opening(user, check_id, body.text, body.purpose, body.amount)


@router.post("/{check_id}/term-confirmation", status_code=status.HTTP_202_ACCEPTED)
async def send_term_confirmation(
    check_id: str, body: Message, user: CurrentUser, runner: Runner
) -> None:
    """The line of a term PUT /term saved; a check with no option and no awaiting offer gets the
    offer form on the event stream with no model call, any other a model turn. The errors are a
    message's."""
    await runner.send_term_confirmation(user, check_id, body.text)


@router.post("/{check_id}/offer-skip", status_code=status.HTTP_202_ACCEPTED)
async def send_offer_skip(check_id: str, body: Message, user: CurrentUser, runner: Runner) -> None:
    """The offer form's skip, answered with an invitation to describe the offer and no model
    call; the reply arrives on the event stream, and the errors are a message's."""
    await runner.send_offer_skip(user, check_id, body.text)


def register_error_handlers(app: FastAPI) -> None:
    async def not_found(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, CheckNotFoundError)
        return JSONResponse({"detail": "no such check"}, status_code=status.HTTP_404_NOT_FOUND)

    async def awaiting_not_found(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, AwaitingOfferNotFoundError)
        return JSONResponse(
            {"detail": "no such awaiting offer"}, status_code=status.HTTP_404_NOT_FOUND
        )

    async def conflict(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, TurnConflictError | CheckArchivedError | CheckNotRestorableError)
        return JSONResponse(
            {"detail": str(error), "check_id": error.check_id},
            status_code=status.HTTP_409_CONFLICT,
        )

    async def unsavable(request: Request, error: Exception) -> JSONResponse:
        """The message names the figure at fault, or what the engine or a tool refused."""
        assert isinstance(error, FinancesError | EngineError | ToolError)
        return JSONResponse(
            {"detail": str(error)}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
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
    app.add_exception_handler(AwaitingOfferNotFoundError, awaiting_not_found)
    app.add_exception_handler(TurnConflictError, conflict)
    app.add_exception_handler(CheckArchivedError, conflict)
    app.add_exception_handler(CheckNotRestorableError, conflict)
    app.add_exception_handler(FinancesError, unsavable)
    app.add_exception_handler(EngineError, unsavable)
    app.add_exception_handler(ToolError, unsavable)
    app.add_exception_handler(TurnLimitError, over_limit)
