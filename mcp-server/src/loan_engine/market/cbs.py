"""Central Bureau of Statistics consumer price index: monthly change of the index with id 120010."""

from datetime import date
from decimal import Decimal

import httpx2

from loan_engine.market.boi import parse_decimal

CPI_URL = "https://api.cbs.gov.il/index/data/price"
_PAGE_SIZE = 1000


async def fetch_cpi(client: httpx2.AsyncClient, start: date) -> list[tuple[date, Decimal]]:
    """Monthly CPI change as a fraction, keyed by month start, oldest first, from start.

    The change comes from the published monthly percent, not from index levels, which restart
    at each base change.
    """
    response = await client.get(
        CPI_URL,
        params={
            "id": 120010,
            "format": "json",
            "download": "false",
            "startPeriod": f"{start.month:02d}-{start.year}",
            "PageSize": _PAGE_SIZE,
        },
    )
    response.raise_for_status()
    body = response.json()
    if body["paging"]["last_page"] > 1:
        raise ValueError(f"CPI response has {body['paging']['last_page']} pages; only one is read")
    points = [
        (date(row["year"], row["month"], 1), parse_decimal(str(row["percent"]), CPI_URL) / 100)
        for row in body["month"][0]["date"]
    ]
    if not points:
        raise ValueError("no CPI observations returned")
    return sorted(points)
