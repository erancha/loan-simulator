"""Sign-in routes and the dependency that names the person behind a request.

The page signs people in with Google and posts the ID token here; the token itself becomes an
HttpOnly cookie that lasts until the token expires, and every protected route verifies it again
on each request. There is no server-side session: the cookie carries the proof, and the browser's
event-stream object, which cannot send headers, carries it too. The token goes no further than
the verifier: routes act for the person it names.

Core building blocks:
- current_user / CurrentUser: the dependency protected routes take; 401 without a valid cookie
- router: /api/auth/config (the public client id), /api/auth/session (sign in, sign out),
  /api/auth/me (who is signed in); a signed-in person is answered with their message status
- register_error_handlers: a missing or bad token answers 401 with the reason
"""

from datetime import UTC, datetime
from typing import Annotated, Self

import structlog
from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from loan_agent.domain.errors import InvalidTokenError
from loan_agent.domain.models import MessageStatus, User, VerifiedToken
from loan_agent.platform.dependencies import Deps, Runner

COOKIE = "ls_id_token"
NOT_SIGNED_IN = "sign in to continue"

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auth")


class NotSignedInError(Exception):
    """The request carries no token at all."""


def current_user(request: Request, deps: Deps) -> User:
    # The cookie is absent on a first visit and after sign-out: a legal state, answered 401.
    token = request.cookies.get(COOKIE)
    if token is None:
        raise NotSignedInError(NOT_SIGNED_IN)
    return deps.verifier.verify(token).user


CurrentUser = Annotated[User, Depends(current_user)]


class CredentialRequest(BaseModel):
    credential: str
    """The ID token Google's redirect hands the page."""


class MessageStatusResponse(BaseModel):
    """The person's standing against the message cap, which counts the messages the model
    answers."""

    limit: int
    left: int
    next_free: datetime | None
    """When the next message frees; null while none is used."""


class UserResponse(BaseModel):
    id: str
    email: str | None
    name: str | None
    messages: MessageStatusResponse

    @classmethod
    def of(cls, user: User, messages: MessageStatus) -> Self:
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            messages=MessageStatusResponse(
                limit=messages.limit, left=messages.left, next_free=messages.next_free
            ),
        )


@router.get("/config")
async def config(deps: Deps) -> dict[str, str]:
    return {"clientId": deps.google_client_id}


@router.post("/session")
async def sign_in(
    body: CredentialRequest, request: Request, response: Response, deps: Deps, runner: Runner
) -> UserResponse:
    verified = deps.verifier.verify(body.credential)
    set_session_cookie(response, request, body.credential, verified, https_only=deps.https_only)
    return UserResponse.of(verified.user, await runner.message_status(verified.user))


@router.get("/me")
async def me(user: CurrentUser, runner: Runner) -> UserResponse:
    return UserResponse.of(user, await runner.message_status(user))


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(response: Response) -> Response:
    response.delete_cookie(COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def set_session_cookie(
    response: Response,
    request: Request,
    token: str,
    verified: VerifiedToken,
    *,
    https_only: bool,
) -> None:
    """The cookie lives exactly as long as the token: once it expires, the next request is 401 and
    the page asks the person to sign in again. It is Secure when the request is https, or when
    the deployment says people reach the agent only over HTTPS that ends before it."""
    remaining = int((verified.expires_at - datetime.now(UTC)).total_seconds())
    response.set_cookie(
        COOKIE,
        token,
        max_age=max(remaining, 0),
        path="/",
        httponly=True,
        samesite="strict",
        secure=https_only or request.url.scheme == "https",
    )


def register_error_handlers(app: FastAPI) -> None:
    async def unauthorized(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, InvalidTokenError | NotSignedInError)
        if isinstance(error, InvalidTokenError):
            # The reason names the failed check, never the token itself.
            log.warning("token refused", path=request.url.path, reason=str(error))
        return JSONResponse(
            {"detail": str(error)},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    app.add_exception_handler(InvalidTokenError, unauthorized)
    app.add_exception_handler(NotSignedInError, unauthorized)
