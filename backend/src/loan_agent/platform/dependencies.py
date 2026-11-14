"""What the HTTP app runs on, and the request dependencies that hand it out.

- Infrastructure: the storage, engine, model and checkpointer the lifespan opens; production
  opens the real ones, tests hand in fakes
- AppDeps: what a request touches
- Deps, Runner, Shutdown: the request dependencies
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import Depends, Request
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver

from loan_agent.platform.check_runner import CheckRunner
from loan_agent.ports.auth import TokenVerifier
from loan_agent.ports.engine import LoanEngine
from loan_agent.ports.events import EventBus, EventSink
from loan_agent.ports.repositories import (
    CheckEventStore,
    CheckRepository,
    OptionRepository,
    ProfileRepository,
    RecommendationRepository,
)


@dataclass(frozen=True)
class Infrastructure:
    profiles: ProfileRepository
    checks: CheckRepository
    options: OptionRepository
    recommendations: RecommendationRepository
    events: CheckEventStore
    engine: LoanEngine
    engine_tools: list[BaseTool]
    """The engine's tools as the model calls them."""
    model: BaseChatModel
    checkpointer: BaseCheckpointSaver[Any]
    ready: Callable[[], Awaitable[None]]
    """The readiness probe: returns while the database answers, raises otherwise."""
    clock: Callable[[], datetime]


@dataclass(frozen=True)
class AppDeps:
    profiles: ProfileRepository
    checks: CheckRepository
    options: OptionRepository
    recommendations: RecommendationRepository
    events: CheckEventStore
    sink: EventSink
    bus: EventBus
    """Carries the events the sink publishes to the open event streams."""
    verifier: TokenVerifier
    google_client_id: str
    """The OAuth client the page signs people in with; published to the page, public."""
    https_only: bool
    """People reach the agent only over HTTPS, whatever scheme its own requests show."""
    ready: Callable[[], Awaitable[None]]
    clock: Callable[[], datetime]


def get_deps(request: Request) -> AppDeps:
    return cast(AppDeps, request.app.state.deps)


def get_runner(request: Request) -> CheckRunner:
    return cast(CheckRunner, request.app.state.runner)


def get_shutdown(request: Request) -> asyncio.Event:
    """Set when the server is asked to stop or the app's lifespan begins its teardown."""
    return cast(asyncio.Event, request.app.state.shutdown)


Deps = Annotated[AppDeps, Depends(get_deps)]
Runner = Annotated[CheckRunner, Depends(get_runner)]
Shutdown = Annotated[asyncio.Event, Depends(get_shutdown)]
