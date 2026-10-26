import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from structlog.testing import capture_logs

from loan_engine.market.refresh import MarketDataUnavailableError, build_history, refresh
from loan_engine.market.store import SeriesStore

# The last two months of the Bank of Israel and CPI fixtures, which share 2022-01..2023-06.
CONSUMER_CSV = "TIME_PERIOD,OBS_VALUE\n2023-05,6.5\n2023-06,6.6\n"


def _serve(fixture_text, failing: set[str] = frozenset()):
    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if "MNT_RIB_BOI_D" in path:
            name, body = "boi_rate", fixture_text("boi_rate.csv")
        elif "BNK_99010_LR_BIR_1893" in path:
            name, body = "consumer_rate", CONSUMER_CSV
        else:
            name, body = "cpi", fixture_text("cpi_overlap.json")
        if name in failing:
            return httpx2.Response(503)
        return httpx2.Response(200, text=body)

    return handler


def test_build_history_aligns_months_present_in_both_series():
    d = Decimal
    daily = [
        (date(1994, 1, 27), d("10.5")),
        (date(1994, 3, 10), d("9.0")),
        (date(1994, 4, 20), d("8.0")),
    ]
    cpi = [
        (date(1994, 1, 1), d("0.007")),
        (date(1994, 2, 1), d("0.01")),
        (date(1994, 3, 1), d("0.02")),
    ]
    consumer = [(date(1994, 2, 1), d("7.0")), (date(1994, 3, 1), d("7.5"))]

    history = build_history(daily, cpi, consumer)

    assert history.months == (date(1994, 2, 1), date(1994, 3, 1))
    assert history.boi_rate == (d("10.5"), d("10.5"))
    assert history.monthly_inflation == (d("0.01"), d("0.02"))
    assert (history.current_boi_rate, history.rate_as_of) == (d("8.0"), date(1994, 4, 20))
    assert history.cpi_as_of == date(1994, 3, 1)
    assert (history.consumer_rate, history.consumer_rate_month) == (d("7.5"), date(1994, 3, 1))
    assert history.consumer_month_prime == d("12.0")


async def test_refresh_saves_fresh_history(make_client, fixture_text, tmp_path: Path):
    store = SeriesStore(tmp_path / "series.json")

    history = await refresh(store, make_client(_serve(fixture_text)))

    assert history.months[0] == date(2022, 1, 1)
    assert history.months[-1] == date(2023, 6, 1)
    assert len(history.months) == 18
    assert history.boi_rate[0] == Decimal("0.1")
    assert history.boi_rate[-1] == Decimal("4.75")
    assert history.consumer_rate == Decimal("6.6")
    assert history.consumer_month_prime == Decimal("6.25")
    assert store.load() == history


async def test_refresh_falls_back_to_stored_history(make_client, fixture_text, tmp_path: Path):
    store = SeriesStore(tmp_path / "series.json")
    stored = await refresh(store, make_client(_serve(fixture_text)))

    with capture_logs() as logs:
        history = await refresh(store, make_client(_serve(fixture_text, {"cpi"})))

    assert history == stored
    (warning,) = [e for e in logs if e["log_level"] == "warning"]
    assert warning["failed_series"] == ["cpi"]
    assert warning["cpi_as_of"] == stored.cpi_as_of.isoformat()
    assert warning["rate_as_of"] == stored.rate_as_of.isoformat()


async def test_refresh_without_store_raises_naming_series(
    make_client, fixture_text, tmp_path: Path
):
    store = SeriesStore(tmp_path / "series.json")

    with pytest.raises(MarketDataUnavailableError, match="boi_rate.*cpi"):
        await refresh(store, make_client(_serve(fixture_text, {"cpi", "boi_rate"})))


async def test_refresh_falls_back_when_series_share_no_month(
    make_client, fixture_text, tmp_path: Path
):
    store = SeriesStore(tmp_path / "series.json")
    stored = await refresh(store, make_client(_serve(fixture_text)))

    def disjoint(request: httpx2.Request) -> httpx2.Response:
        if "price" in request.url.path:
            return httpx2.Response(200, text=fixture_text("cpi.json"))
        return _serve(fixture_text)(request)

    with capture_logs() as logs:
        history = await refresh(store, make_client(disjoint))

    assert history == stored
    assert store.load() == stored
    (warning,) = [e for e in logs if e["log_level"] == "warning"]
    assert warning["failed_series"] == ["series_alignment"]


def test_build_history_names_spans_when_series_share_no_month():
    d = Decimal
    with pytest.raises(ValueError, match=r"rate 1994-02..1994-03, CPI 2000-01..2000-01"):
        build_history(
            [(date(1994, 1, 27), d("1")), (date(1994, 3, 10), d("1"))],
            [(date(2000, 1, 1), d("0.01"))],
            [(date(1994, 3, 1), d("7"))],
        )


def test_build_history_rejects_consumer_month_outside_rate_range():
    d = Decimal
    with pytest.raises(ValueError, match=r"consumer rate month 2000-01 .* 1994-02..1994-03"):
        build_history(
            [(date(1994, 1, 27), d("1")), (date(1994, 3, 10), d("1"))],
            [(date(1994, 2, 1), d("0.01"))],
            [(date(2000, 1, 1), d("7"))],
        )


def test_build_history_rejects_a_month_missing_mid_series():
    d = Decimal
    daily = [(date(1994, 1, 27), d("1")), (date(1994, 5, 10), d("1"))]
    cpi = [(date(1994, m, 1), d("0.01")) for m in (2, 3, 5)]
    with pytest.raises(ValueError, match=r"1994-03 is followed by 1994-05"):
        build_history(daily, cpi, [(date(1994, 3, 1), d("7"))])


async def test_refresh_falls_back_when_a_month_is_missing_mid_series(
    make_client, fixture_text, tmp_path: Path
):
    store = SeriesStore(tmp_path / "series.json")
    stored = await refresh(store, make_client(_serve(fixture_text)))
    cpi = json.loads(fixture_text("cpi_overlap.json"))
    points = cpi["month"][0]["date"]
    points[:] = [p for p in points if (p["year"], p["month"]) != (2022, 6)]

    def gapped(request: httpx2.Request) -> httpx2.Response:
        if "price" in request.url.path:
            return httpx2.Response(200, text=json.dumps(cpi))
        return _serve(fixture_text)(request)

    with capture_logs() as logs:
        history = await refresh(store, make_client(gapped))

    assert history == stored
    (warning,) = [e for e in logs if e["log_level"] == "warning"]
    assert warning["failed_series"] == ["series_alignment"]
    assert "2022-05 is followed by 2022-07" in warning["errors"]["series_alignment"]
