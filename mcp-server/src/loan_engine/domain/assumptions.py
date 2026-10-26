"""Modelling assumptions that are choices, not market data; docs/calculations.md gives reasons."""

from datetime import date
from decimal import Decimal

HISTORY_START = date(2000, 1, 1)
BASE_ANNUAL_INFLATION = Decimal("2.0")
PRIME_MARGIN = Decimal("1.5")
BOI_RATE_FLOOR = Decimal(0)

STABLE_VARIABLE_SHARE = Decimal("0.5")
INCOME_SHARE_CAP = Decimal("0.30")
DISPOSABLE_SHARE_CAP = Decimal("0.50")
CUSHION_MONTHS = 2
