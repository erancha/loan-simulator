"""Modelling assumptions that are choices, not market data; docs/calculations.md gives reasons."""

from decimal import Decimal

HISTORY_MONTHS = 120
# The future the engine assumes for today's figures: the CPI rises DEFAULT_CPI_PER_YEAR percent a
# year and prime stays where it is.
DEFAULT_CPI_PER_YEAR = Decimal("2.0")
DEFAULT_PRIME_PER_YEAR = Decimal(0)
PRIME_MARGIN = Decimal("1.5")
BOI_RATE_FLOOR = Decimal(0)

INCOME_SHARE_CAP = Decimal("0.30")
DISPOSABLE_SHARE_CAP = Decimal("0.50")

# An unlinked rate within SIMILAR_RATE_POINTS percentage points of the average consumer rate is
# similar to it; further off it is above or below.
SIMILAR_RATE_POINTS = Decimal("0.25")

# A suggested term is searched in steps of TERM_STEP months.
TERM_STEP = 6
# The largest loan a payment ceiling carries is named to a whole LOAN_STEP shekels.
LOAN_STEP = 1000

# A pension, provident or study fund lends its members against their savings at a fixed rate
# linked to the CPI. A large Israeli pension fund publishes 3.5% or 4% a year plus the CPI,
# depending on underwriting, for up to 84 months and up to 30% of the fund's balance. The pension
# fund track of suggest_tracks takes the upper end, so it never promises the better
# underwriting result.
PENSION_FUND_RATE = Decimal(4)
