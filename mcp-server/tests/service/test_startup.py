import asyncio
from datetime import timedelta

import pytest
from starlette.applications import Starlette

from loan_engine.__main__ import run
from loan_engine.domain.history import MarketHistory
from loan_engine.market.refresh import MarketDataUnavailableError
from loan_engine.service.config import Settings

HOURLY = timedelta(hours=1)


async def test_refreshes_once_before_serving(settings: Settings, history: MarketHistory) -> None:
    refreshes_before_serving: list[int] = []
    calls = 0

    async def refresher() -> MarketHistory:
        nonlocal calls
        calls += 1
        return history

    async def serve(app: Starlette) -> None:
        assert isinstance(app, Starlette)
        refreshes_before_serving.append(calls)

    await run(settings, refresher, serve, HOURLY)
    assert refreshes_before_serving == [1]


async def test_unavailable_market_data_aborts_startup(settings: Settings) -> None:
    served = False

    async def refresher() -> MarketHistory:
        raise MarketDataUnavailableError("no stored market data and these series failed: cpi")

    async def serve(app: Starlette) -> None:
        nonlocal served
        served = True

    with pytest.raises(MarketDataUnavailableError, match="cpi"):
        await run(settings, refresher, serve, HOURLY)
    assert not served


async def test_failing_daily_refresh_ends_the_server(
    settings: Settings, history: MarketHistory
) -> None:
    calls = 0

    async def refresher() -> MarketHistory:
        nonlocal calls
        calls += 1
        if calls == 1:
            return history
        raise OSError("disk full")

    async def serve_forever(app: Starlette) -> None:
        await asyncio.Event().wait()

    with pytest.raises(ExceptionGroup) as error:
        await asyncio.wait_for(run(settings, refresher, serve_forever, timedelta(0)), timeout=5)
    assert error.group_contains(OSError, match="disk full")
