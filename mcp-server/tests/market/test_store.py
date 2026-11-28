"""SeriesStore restores the history it saved and keeps the stored file when a save fails."""

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from loan_engine.domain.history import MarketHistory
from loan_engine.market.store import SeriesStore

FETCHED_AT = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)


def _history(rate: str = "3.25") -> MarketHistory:
    return MarketHistory(
        months=(date(2026, 8, 1), date(2026, 9, 1)),
        boi_rate=(Decimal("4.5"), Decimal(rate)),
        monthly_inflation=(Decimal("0.003"), Decimal("-0.005")),
        current_boi_rate=Decimal(rate),
        rate_as_of=date(2026, 10, 26),
        cpi_as_of=date(2026, 9, 1),
        consumer_rate=Decimal("7.9"),
        consumer_rate_month=date(2026, 8, 1),
        consumer_month_prime=Decimal("6.0"),
    )


def test_load_without_file_returns_none(tmp_path: Path):
    assert SeriesStore(tmp_path / "series.json").load() is None


def test_store_round_trip(tmp_path: Path):
    store = SeriesStore(tmp_path / "series.json")

    store.save(_history(), FETCHED_AT)

    assert store.load() == _history()


def test_store_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "series.json"
    store = SeriesStore(path)
    store.save(_history("3.25"), FETCHED_AT)

    def fail(src: str, dst: Path) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.save(_history("4.0"), FETCHED_AT)
    monkeypatch.undo()

    assert store.load() == _history("3.25")
    assert [p.name for p in tmp_path.iterdir()] == ["series.json"]
