"""Fetches the market series, builds a MarketHistory and keeps it, falling back to the stored one.

- build_history(): aligns the daily rate, CPI and consumer-rate series into a MarketHistory
- refresh(): fetches, saves on success, and returns the stored history when a fetch or the
  alignment fails
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx2
import structlog

from loan_engine.domain.assumptions import PRIME_MARGIN
from loan_engine.domain.history import MarketHistory
from loan_engine.market.boi import boi_monthly, fetch_boi, fetch_consumer_rate
from loan_engine.market.cbs import fetch_cpi
from loan_engine.market.store import SeriesStore

_log = structlog.get_logger()

_SERIES_START = date(1994, 1, 1)
_CONSUMER_RATE_LOOKBACK_MONTHS = 24

_Series = list[tuple[date, Decimal]]


class MarketDataUnavailableError(RuntimeError):
    pass


def build_history(daily_boi: _Series, cpi: _Series, consumer: _Series) -> MarketHistory:
    """Monthly points are the months in both the Bank of Israel monthly series and the CPI."""
    monthly_boi = dict(boi_monthly(daily_boi))
    inflation = dict(cpi)
    months = tuple(sorted(monthly_boi.keys() & inflation.keys()))
    if not months:
        raise ValueError(
            "Bank of Israel rate and CPI share no month: rate "
            f"{min(monthly_boi):%Y-%m}..{max(monthly_boi):%Y-%m}, "
            f"CPI {min(inflation):%Y-%m}..{max(inflation):%Y-%m}"
        )
    consumer_month, consumer_rate = consumer[-1]
    if consumer_month not in monthly_boi:
        raise ValueError(
            f"consumer rate month {consumer_month:%Y-%m} is outside the Bank of Israel rate "
            f"range {min(monthly_boi):%Y-%m}..{max(monthly_boi):%Y-%m}"
        )
    rate_as_of, current_boi_rate = daily_boi[-1]
    return MarketHistory(
        months=months,
        boi_rate=tuple(monthly_boi[m] for m in months),
        monthly_inflation=tuple(inflation[m] for m in months),
        current_boi_rate=current_boi_rate,
        rate_as_of=rate_as_of,
        cpi_as_of=cpi[-1][0],
        consumer_rate=consumer_rate,
        consumer_rate_month=consumer_month,
        consumer_month_prime=monthly_boi[consumer_month] + PRIME_MARGIN,
    )


async def refresh(store: SeriesStore, client: httpx2.AsyncClient) -> MarketHistory:
    """Fetch and save fresh market data, or return the stored history if a series fails to fetch
    or the series fail to align.

    Raises MarketDataUnavailableError naming the failed series when nothing is stored.
    """
    today = date.today()
    consumer_start = _months_back(today, _CONSUMER_RATE_LOOKBACK_MONTHS)
    failed: dict[str, Exception] = {}
    fetched: dict[str, _Series] = {}
    fetches: dict[str, Callable[[], Awaitable[_Series]]] = {
        "boi_rate": lambda: fetch_boi(client, _SERIES_START),
        "cpi": lambda: fetch_cpi(client, _SERIES_START),
        "consumer_rate": lambda: fetch_consumer_rate(client, consumer_start),
    }
    for name, fetch in fetches.items():
        try:
            fetched[name] = await fetch()
        except (httpx2.HTTPError, ValueError, KeyError) as error:
            failed[name] = error

    history = None
    if not failed:
        try:
            history = build_history(fetched["boi_rate"], fetched["cpi"], fetched["consumer_rate"])
        except ValueError as error:
            failed["series_alignment"] = error
    if history is not None:
        store.save(history, datetime.now(UTC))
        _log.info("market data refreshed", **_data_dates(history))
        return history

    names = sorted(failed)
    stored = store.load()
    if stored is None:
        raise MarketDataUnavailableError(
            f"no stored market data and these series failed: {', '.join(names)}"
        ) from next(iter(failed.values()))
    _log.warning(
        "market data fetch failed; using stored data",
        failed_series=names,
        errors={name: repr(error) for name, error in failed.items()},
        **_data_dates(stored),
    )
    return stored


def _data_dates(history: MarketHistory) -> dict[str, str]:
    return {
        "rate_as_of": history.rate_as_of.isoformat(),
        "cpi_as_of": history.cpi_as_of.isoformat(),
        "consumer_rate_month": history.consumer_rate_month.isoformat(),
    }


def _months_back(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)
