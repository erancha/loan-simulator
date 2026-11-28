"""The Bank of Israel fetchers parse the recorded CSV and refuse a malformed number; boi_monthly()
takes the rate in effect on each first of month."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import httpx2
import pytest

from loan_engine.market.boi import boi_monthly, fetch_boi, fetch_consumer_rate, parse_decimal


async def test_boi_parses_csv_and_sends_browser_user_agent(
    make_client, fixture_text, requests_seen
):
    client = make_client(lambda r: httpx2.Response(200, text=fixture_text("boi_rate.csv")))

    daily = await fetch_boi(client, date(2021, 12, 1))

    assert daily[0] == (date(2021, 12, 1), Decimal("0.1"))
    assert (date(2023, 6, 30), Decimal("4.75")) == daily[-1]
    (request,) = requests_seen
    assert request.url.params["startperiod"] == "2021-12-01"
    assert request.url.params["format"] == "csv"
    assert request.headers["User-Agent"].startswith("Mozilla/5.0")


def test_boi_monthly_uses_last_value_on_or_before_first_of_month():
    daily = [
        (date(2022, 3, 31), Decimal("0.1")),  # Thursday
        (date(2022, 4, 4), Decimal("0.1")),  # first and second of April are the weekend
        (date(2022, 4, 5), Decimal("0.35")),
        (date(2022, 5, 1), Decimal("0.35")),
        (date(2022, 5, 5), Decimal("0.75")),
        (date(2022, 5, 20), Decimal("0.75")),
    ]

    assert boi_monthly(daily) == [
        (date(2022, 4, 1), Decimal("0.1")),
        (date(2022, 5, 1), Decimal("0.35")),
    ]


def test_boi_monthly_starts_after_a_mid_month_first_value():
    daily = [(date(1994, 1, 27), Decimal("10.5")), (date(1994, 2, 3), Decimal("10.5"))]

    assert boi_monthly(daily) == [(date(1994, 2, 1), Decimal("10.5"))]


async def test_consumer_rate_parses_latest_month(make_client, fixture_text):
    client = make_client(lambda r: httpx2.Response(200, text=fixture_text("consumer_rate.csv")))

    points = await fetch_consumer_rate(client, date(2025, 9, 1))

    assert len(points) == 12
    assert points[-1] == (date(2026, 8, 1), Decimal("7.9"))


async def test_unreachable_source_raises(make_client: Callable[..., httpx2.AsyncClient]):
    client = make_client(lambda r: httpx2.Response(403))

    try:
        await fetch_boi(client, date(2021, 12, 1))
    except httpx2.HTTPError:
        return
    raise AssertionError("expected HTTPError")


async def test_malformed_number_raises_value_error_naming_value(make_client):
    csv_text = "TIME_PERIOD,OBS_VALUE\n2023-06-01,abc\n"
    client = make_client(lambda r: httpx2.Response(200, text=csv_text))

    with pytest.raises(ValueError, match="'abc'"):
        await fetch_boi(client, date(2023, 6, 1))


@pytest.mark.parametrize("text", ["NaN", "-Infinity", "inf", "sNaN"])
def test_non_finite_number_raises_value_error_naming_series_and_value(text):
    with pytest.raises(ValueError, match=f"^MNT_RIB_BOI_D: malformed number '{text}'$"):
        parse_decimal(text, "MNT_RIB_BOI_D")
