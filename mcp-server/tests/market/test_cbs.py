import json
from datetime import date
from decimal import Decimal

import httpx2
import pytest

from loan_engine.market.cbs import fetch_cpi


async def test_cpi_requests_page_size_1000_and_parses_percent(
    make_client, fixture_text, requests_seen
):
    client = make_client(lambda r: httpx2.Response(200, text=fixture_text("cpi.json")))

    points = await fetch_cpi(client, date(2024, 10, 1))

    assert points[0] == (date(2024, 10, 1), Decimal("0.005"))
    assert points[-1] == (date(2025, 3, 1), Decimal("0.005"))
    (request,) = requests_seen
    assert request.url.params["PageSize"] == "1000"
    assert request.url.params["id"] == "120010"
    assert request.url.params["startPeriod"] == "10-2024"


async def test_cpi_chains_across_base_change(make_client, fixture_text):
    client = make_client(lambda r: httpx2.Response(200, text=fixture_text("cpi.json")))

    points = await fetch_cpi(client, date(2024, 10, 1))

    # Index levels fall from 108.4 (base 2022) to 101.5 (base 2024) between 2024-12 and 2025-01;
    # the monthly change in 2025-01 is the published +0.6%, not the level jump.
    assert dict(points)[date(2025, 1, 1)] == Decimal("0.006")
    assert [m for m, _ in points] == sorted(m for m, _ in points)
    assert all(abs(change) < Decimal("0.01") for _, change in points)


async def test_cpi_with_more_than_one_page_fails_loudly(make_client, fixture_text):
    body = json.loads(fixture_text("cpi.json"))
    body["paging"]["last_page"] = 2
    client = make_client(lambda r: httpx2.Response(200, json=body))

    with pytest.raises(ValueError, match="pages"):
        await fetch_cpi(client, date(2024, 10, 1))


async def test_cpi_malformed_percent_raises_value_error(make_client, fixture_text):
    body = json.loads(fixture_text("cpi.json"))
    body["month"][0]["date"][0]["percent"] = "abc"
    client = make_client(lambda r: httpx2.Response(200, json=body))

    with pytest.raises(ValueError, match="'abc'"):
        await fetch_cpi(client, date(2024, 10, 1))
