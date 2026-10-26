"""Bank of Israel series: the daily policy rate and the monthly consumer-loan rate."""

import csv
import io
from bisect import bisect_right
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx2

_DATAFLOW_URL = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS"
BOI_RATE_URL = f"{_DATAFLOW_URL}/BR/1.0/MNT_RIB_BOI_D"
CONSUMER_RATE_SERIES = "BNK_99010_LR_BIR_1893"
CONSUMER_RATE_URL = f"{_DATAFLOW_URL}/BIR/1.0/{CONSUMER_RATE_SERIES}"

# The Bank of Israel rejects the default library User-Agent.
_HEADERS = {"User-Agent": "Mozilla/5.0"}


async def fetch_boi(client: httpx2.AsyncClient, start: date) -> list[tuple[date, Decimal]]:
    """Daily Bank of Israel rate in percent, oldest first, from start."""
    rows = await _fetch_csv(client, BOI_RATE_URL, start)
    return [(date.fromisoformat(period), value) for period, value in rows]


async def fetch_consumer_rate(
    client: httpx2.AsyncClient, start: date
) -> list[tuple[date, Decimal]]:
    """Monthly average rate in percent on new household consumer loans, keyed by month start."""
    rows = await _fetch_csv(client, CONSUMER_RATE_URL, start)
    return [(date.fromisoformat(f"{period}-01"), value) for period, value in rows]


def boi_monthly(daily: list[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    """Rate in effect on each first of month: the latest daily value on or before it.

    Covers the first-of-month dates from the first daily value through the last daily date.
    """
    days = [d for d, _ in daily]
    values = [v for _, v in daily]
    result = []
    month = date(days[0].year, days[0].month, 1)
    if month < days[0]:
        month = _next_month(month)
    while month <= days[-1]:
        result.append((month, values[bisect_right(days, month) - 1]))
        month = _next_month(month)
    return result


def parse_decimal(text: str, series: str) -> Decimal:
    """A finite number; NaN and infinities are malformed like any other non-number."""
    try:
        value = Decimal(text)
    except InvalidOperation:
        value = None
    if value is None or not value.is_finite():
        raise ValueError(f"{series}: malformed number {text!r}")
    return value


def _next_month(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


async def _fetch_csv(
    client: httpx2.AsyncClient, url: str, start: date
) -> list[tuple[str, Decimal]]:
    response = await client.get(
        url, params={"startperiod": start.isoformat(), "format": "csv"}, headers=_HEADERS
    )
    response.raise_for_status()
    rows = [
        (row["TIME_PERIOD"], parse_decimal(row["OBS_VALUE"], url))
        for row in csv.DictReader(io.StringIO(response.text))
    ]
    if not rows:
        raise ValueError(f"no observations returned from {url}")
    return sorted(rows)
