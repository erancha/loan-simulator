"""Startup: load settings, refresh market data, keep it fresh daily and serve the MCP app.

- run(): one refresh, then the server and the daily refresh side by side
- main(): wires run() to the market data sources and uvicorn

Startup fails when no market data can be fetched and none is stored. A daily refresh that raises
ends the server, so the process exits with the error instead of serving on without updates.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

import httpx2
import uvicorn
from starlette.applications import Starlette

from loan_engine.domain.history import MarketHistory
from loan_engine.market.refresh import refresh
from loan_engine.market.store import SeriesStore
from loan_engine.service.config import Settings
from loan_engine.service.server import build_app, build_server

_REFRESH_INTERVAL = timedelta(days=1)
# The daily Bank of Israel series since 1994 is a large CSV.
_FETCH_TIMEOUT = timedelta(seconds=60)
# The server runs in a container and is reached over the Compose network.
_LISTEN_HOST = "0.0.0.0"

Refresher = Callable[[], Awaitable[MarketHistory]]


class LatestHistory:
    """The market history the tools read; replaced after each daily refresh."""

    def __init__(self, history: MarketHistory) -> None:
        self.history = history

    def __call__(self) -> MarketHistory:
        return self.history


async def _refresh_daily(refresher: Refresher, latest: LatestHistory, interval: timedelta) -> None:
    while True:
        await asyncio.sleep(interval.total_seconds())
        latest.history = await refresher()


async def run(
    settings: Settings,
    refresher: Refresher,
    serve: Callable[[Starlette], Awaitable[None]],
    interval: timedelta = _REFRESH_INTERVAL,
) -> None:
    """Serve until serve returns; a failing refresh cancels serve and raises an ExceptionGroup."""
    latest = LatestHistory(await refresher())
    app = build_app(build_server(settings, latest), settings)
    async with asyncio.TaskGroup() as tasks:
        refreshing = tasks.create_task(_refresh_daily(refresher, latest, interval))
        await serve(app)
        refreshing.cancel()


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    store = SeriesStore(settings.data_dir / "market.json")
    async with httpx2.AsyncClient(timeout=_FETCH_TIMEOUT.total_seconds()) as client:

        async def serve(app: Starlette) -> None:
            config = uvicorn.Config(app, host=_LISTEN_HOST, port=settings.port)
            await uvicorn.Server(config).serve()

        await run(settings, lambda: refresh(store, client), serve)


if __name__ == "__main__":
    asyncio.run(main())
