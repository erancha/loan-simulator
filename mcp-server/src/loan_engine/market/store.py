"""Persistence of the last good MarketHistory as one JSON file, replaced atomically."""

import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from loan_engine.domain.history import MarketHistory


class SeriesStore:
    """Holds one MarketHistory at path; a reader sees the old file or the new, never a mix."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def save(self, history: MarketHistory, fetched_at: datetime) -> None:
        document = {
            "fetched_at": fetched_at.isoformat(),
            "months": [d.isoformat() for d in history.months],
            "boi_rate": [str(v) for v in history.boi_rate],
            "monthly_inflation": [str(v) for v in history.monthly_inflation],
            "current_boi_rate": str(history.current_boi_rate),
            "rate_as_of": history.rate_as_of.isoformat(),
            "cpi_as_of": history.cpi_as_of.isoformat(),
            "consumer_rate": str(history.consumer_rate),
            "consumer_rate_month": history.consumer_rate_month.isoformat(),
            "consumer_month_prime": str(history.consumer_month_prime),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp:
                json.dump(document, temp)
            os.replace(temp_name, self._path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def load(self) -> MarketHistory | None:
        """The stored history, or None when nothing has been saved yet."""
        if not self._path.exists():
            return None
        document = json.loads(self._path.read_text(encoding="utf-8"))
        return MarketHistory(
            months=tuple(date.fromisoformat(d) for d in document["months"]),
            boi_rate=tuple(Decimal(v) for v in document["boi_rate"]),
            monthly_inflation=tuple(Decimal(v) for v in document["monthly_inflation"]),
            current_boi_rate=Decimal(document["current_boi_rate"]),
            rate_as_of=date.fromisoformat(document["rate_as_of"]),
            cpi_as_of=date.fromisoformat(document["cpi_as_of"]),
            consumer_rate=Decimal(document["consumer_rate"]),
            consumer_rate_month=date.fromisoformat(document["consumer_rate_month"]),
            consumer_month_prime=Decimal(document["consumer_month_prime"]),
        )
