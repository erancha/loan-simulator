"""The FastAPI application and the composition of its production dependencies.

Core building blocks:
- create_app: routes (sign-in, checks, profile, events), error mapping and probes; its lifespan
  opens the infrastructure, builds the event sink, the agent graph and the CheckRunner, and ends
  the turns a stopped process left running before the app serves
- production_infrastructure: the engine adapter (which must list its tools), the chat model, the
  Postgres checkpointer, the database engine and the Postgres repositories, closed in reverse
  order on shutdown
- /health answers while the process runs; /ready also needs the database to answer SELECT 1
- signal_shutdown: tells open event streams to end when the server is asked to stop

Uvicorn runs it as a factory: uvicorn loan_agent.platform.app:create_app --factory.
"""

import asyncio
import signal
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import Any

import structlog
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from loan_agent.adapters.chat_model import build_chat_model
from loan_agent.adapters.engine_mcp import McpLoanEngine
from loan_agent.adapters.google_tokens import GoogleTokenVerifier, JwksKeys, StaticKey
from loan_agent.adapters.memory_bus import InMemoryEventBus
from loan_agent.adapters.postgres.repositories import (
    PostgresCheckEventStore,
    PostgresCheckRepository,
    PostgresOptionRepository,
    PostgresProfileRepository,
    PostgresRecommendationRepository,
)
from loan_agent.application.agent_graph import build_agent_graph
from loan_agent.application.check_tools import ToolDeps
from loan_agent.application.event_sink import CheckEventSink
from loan_agent.platform.api import auth, checks, events, profile
from loan_agent.platform.check_runner import CheckRunner
from loan_agent.platform.checkpointer import libpq_dsn, open_checkpointer
from loan_agent.platform.config import Settings, get_settings
from loan_agent.platform.db import build_engine, session_factory
from loan_agent.platform.dependencies import AppDeps, Deps, Infrastructure
from loan_agent.platform.logging import configure_logging

log = structlog.get_logger(__name__)

OpenInfrastructure = Callable[[Settings], AbstractAsyncContextManager[Infrastructure]]


class EngineUnreachableError(RuntimeError):
    """The loan engine did not list its tools, so the agent cannot serve a turn."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def token_verifier(settings: Settings) -> GoogleTokenVerifier:
    """Google's published keys, unless a public key file stands in for them (tests only)."""
    keys = (
        JwksKeys(settings.auth_jwks_url)
        if settings.auth_public_key_file is None
        else StaticKey.from_file(settings.auth_public_key_file)
    )
    return GoogleTokenVerifier(settings.google_client_id, settings.auth_issuer, keys)


@asynccontextmanager
async def production_infrastructure(settings: Settings) -> AsyncIterator[Infrastructure]:
    """The engine is asked for its tools first, so an unreachable engine fails startup before any
    database connection opens."""
    engine = McpLoanEngine(settings.engine_url, settings.engine_bearer_token.get_secret_value())
    try:
        engine_tools = await engine.model_tools()
    except Exception as error:
        raise EngineUnreachableError(
            f"the loan engine at {settings.engine_url} did not list its tools ({error!r}); "
            "check that it runs, and ENGINE_URL and ENGINE_BEARER_TOKEN"
        ) from error
    model = build_chat_model(settings.llm_model, settings.llm_api_key.get_secret_value())
    database_url = settings.database_url.get_secret_value()
    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(open_checkpointer(libpq_dsn(database_url)))
        database = build_engine(database_url)
        stack.push_async_callback(database.dispose)
        sessions = session_factory(database)

        async def ready() -> None:
            async with sessions() as session:
                await session.execute(text("SELECT 1"))

        yield Infrastructure(
            profiles=PostgresProfileRepository(sessions, utc_now),
            checks=PostgresCheckRepository(sessions),
            options=PostgresOptionRepository(sessions),
            recommendations=PostgresRecommendationRepository(sessions),
            events=PostgresCheckEventStore(sessions),
            engine=engine,
            engine_tools=engine_tools,
            model=model,
            checkpointer=checkpointer,
            ready=ready,
            clock=utc_now,
        )


SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM)


@contextmanager
def signal_shutdown(shutdown: asyncio.Event) -> Iterator[None]:
    """Set the shutdown event on SIGINT or SIGTERM, then hand the signal to the prior handler.

    Uvicorn waits for open responses to finish before it runs the lifespan teardown, so an event
    stream that only learnt of shutdown there would hold the server open forever. Python lets
    only the main thread install handlers; off it (TestClient runs the lifespan in a worker
    thread) the lifespan teardown is the only trigger.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    loop = asyncio.get_running_loop()
    prior = {sig: _restorable(signal.getsignal(sig)) for sig in SHUTDOWN_SIGNALS}

    def handle(sig: int, frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(shutdown.set)
        previous = prior[signal.Signals(sig)]
        if callable(previous):
            previous(sig, frame)
        else:
            signal.signal(sig, previous)
            signal.raise_signal(sig)

    for sig in SHUTDOWN_SIGNALS:
        signal.signal(sig, handle)
    try:
        yield
    finally:
        for sig, previous in prior.items():
            signal.signal(sig, previous)


def _restorable(
    handler: Callable[[int, FrameType | None], Any] | int | None,
) -> Callable[[int, FrameType | None], Any] | int:
    """getsignal answers None for a handler installed outside Python, which cannot be put back;
    the default action is the closest restorable handler."""
    return signal.SIG_DFL if handler is None else handler


def create_app(
    settings: Settings | None = None, infrastructure: OpenInfrastructure | None = None
) -> FastAPI:
    """Without infrastructure the app is the production process: it configures logging and opens
    the production infrastructure, with settings read from the environment when not given."""
    if settings is None:
        settings = get_settings()
    if infrastructure is None:
        configure_logging(settings.agent_log_level)
        infrastructure = production_infrastructure
    verifier = token_verifier(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            opened = await stack.enter_async_context(infrastructure(settings))
            bus = InMemoryEventBus()
            sink = CheckEventSink(opened.events, bus)
            tool_deps = ToolDeps(
                profiles=opened.profiles,
                checks=opened.checks,
                options=opened.options,
                recommendations=opened.recommendations,
                engine=opened.engine,
                sink=sink,
                clock=opened.clock,
                new_id=lambda: str(uuid.uuid4()),
            )
            graph = build_agent_graph(
                opened.model, opened.engine_tools, tool_deps, opened.checkpointer
            )
            runner = CheckRunner(
                graph,
                opened.checks,
                opened.events,
                sink,
                turn_limit=settings.agent_turn_limit,
                turn_limit_overrides=settings.agent_turn_limit_overrides,
                window=timedelta(hours=settings.agent_turn_window_hours),
                clock=opened.clock,
            )
            stack.push_async_callback(runner.aclose)
            await runner.fail_interrupted()
            shutdown = asyncio.Event()
            app.state.deps = AppDeps(
                profiles=opened.profiles,
                checks=opened.checks,
                options=opened.options,
                recommendations=opened.recommendations,
                events=opened.events,
                bus=bus,
                verifier=verifier,
                google_client_id=settings.google_client_id,
                ready=opened.ready,
                clock=opened.clock,
            )
            app.state.runner = runner
            app.state.shutdown = shutdown
            try:
                with signal_shutdown(shutdown):
                    yield
            finally:
                shutdown.set()

    app = FastAPI(title="Loan agent", lifespan=lifespan)
    auth.register_error_handlers(app)
    checks.register_error_handlers(app)
    profile.register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(checks.router)
    app.include_router(profile.router)
    app.include_router(events.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(wired: Deps) -> JSONResponse:
        """Any failure of the probe query means not ready; the cause is logged."""
        try:
            await wired.ready()
        except Exception:
            log.warning("readiness probe failed", exc_info=True)
            return JSONResponse(
                {"status": "not ready"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        return JSONResponse({"status": "ok"})

    # After the routers, so API paths take precedence over the catch-all mount.
    if settings.agent_frontend_dist is not None:
        _mount_frontend(app, settings.agent_frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serves the built page's folder at /; refuses a folder without index.html."""
    if not (dist / "index.html").is_file():
        raise FileNotFoundError(f"AGENT_FRONTEND_DIST={dist} has no index.html; build the frontend")
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
