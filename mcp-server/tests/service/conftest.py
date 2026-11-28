"""Fixtures of the service tests: a synthetic market history and the engine's settings."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import SecretStr

from loan_engine.domain.history import MarketHistory
from loan_engine.service.config import Settings

TOKEN = "t" * 32
PORT = 8020
HOST = f"engine:{PORT}"
PUBLIC_URL = f"http://{HOST}"
HISTORY_MONTHS = 120


def make_history(months: int) -> MarketHistory:
    """Monthly series from 2000-01 with a Bank of Israel rate that rises and falls."""
    return MarketHistory(
        months=tuple(date(2000 + i // 12, i % 12 + 1, 1) for i in range(months)),
        boi_rate=tuple(Decimal(i % 40) / 8 for i in range(months)),
        monthly_inflation=tuple(Decimal("0.002") for _ in range(months)),
        current_boi_rate=Decimal("3.25"),
        rate_as_of=date(2026, 10, 20),
        cpi_as_of=date(2026, 9, 1),
        consumer_rate=Decimal("7.9"),
        consumer_rate_month=date(2026, 8, 1),
        consumer_month_prime=Decimal("5.0"),
    )


@pytest.fixture
def history() -> MarketHistory:
    return make_history(HISTORY_MONTHS)


@pytest.fixture
def short_history() -> MarketHistory:
    """Too short for a 48-month window."""
    return make_history(30)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bearer_token=SecretStr(TOKEN), allowed_hosts=[HOST], public_url=PUBLIC_URL, port=PORT
    )
