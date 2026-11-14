"""Profile routes: the person reads their finances with what is still missing, and corrects them.

An edit that changes a figure archives every check recommended from the replaced figures.
"""

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse

from loan_agent.application.profile_saving import save_profile
from loan_agent.domain.errors import ProfileError
from loan_agent.platform.api.auth import CurrentUser
from loan_agent.platform.api.schemas import ProfileUpdate, ProfileView
from loan_agent.platform.dependencies import Deps

router = APIRouter(prefix="/api/profile")


@router.get("")
async def get_profile(user: CurrentUser, deps: Deps) -> ProfileView:
    profile, _ = await deps.profiles.get(user.id)
    return ProfileView.of(profile)


@router.put("")
async def update_profile(body: ProfileUpdate, user: CurrentUser, deps: Deps) -> ProfileView:
    saved = await save_profile(
        user.id, body.sent(), deps.profiles, deps.checks, deps.sink, deps.clock
    )
    return ProfileView.of(saved.profile)


def register_error_handlers(app: FastAPI) -> None:
    async def invalid(request: Request, error: Exception) -> JSONResponse:
        """The message names the field at fault."""
        assert isinstance(error, ProfileError)
        return JSONResponse(
            {"detail": str(error)}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )

    app.add_exception_handler(ProfileError, invalid)
