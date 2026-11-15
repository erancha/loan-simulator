"""The answer to the page's market-data sample, written from the engine's data with no model call:
the prime over the last five years and the CPI over the last year, each as a chart and a line.

- chart_data: a series' points as the chart.shown event carries them, shared with show_chart
- market_answer: the two lines of text and the two charts of the answer

The data changes only when the Bank of Israel moves its rate or a month's CPI is published, so a
model would only reword the same figures; the code states them exactly.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from math import prod
from typing import Any

from loan_agent.ports.engine import MarketPoint, MarketSeries

PRIME_MONTHS = 60
CPI_MONTHS = 12

_ONE_DECIMAL = Decimal("0.1")
# Each figure is a left-to-right island in the Hebrew text, so its sign, percent mark and
# separators stay in place beside the punctuation around it.
_ISOLATE_START = "\u2066"
_ISOLATE_END = "\u2069"


def chart_data(series: str, points: tuple[MarketPoint, ...], as_of: date) -> dict[str, Any]:
    return {
        "series": series,
        "as_of": as_of.isoformat(),
        "points": [{"month": p.month.isoformat(), "value": str(p.value)} for p in points],
    }


def market_answer(market: MarketSeries) -> tuple[str, list[dict[str, Any]]]:
    """The text and the chart.shown data of the answer. market holds PRIME_MONTHS of each
    series."""
    assert len(market.prime) == PRIME_MONTHS, "the prime line speaks of five years"
    cpi = market.cpi_change[-CPI_MONTHS:]
    text = f"{_prime_line(market.prime, market.rate_as_of)}\n\n{_cpi_line(cpi)}"
    charts = [
        chart_data("prime", market.prime, market.rate_as_of),
        chart_data("cpi", cpi, market.cpi_as_of),
    ]
    return text, charts


def _prime_line(points: tuple[MarketPoint, ...], as_of: date) -> str:
    """The series holds the prime on the first of each month, so the line states the changes
    between months, never the day of one."""
    values = [point.value for point in points]
    current = f"ריבית הפריים נכון ל-{_figure(f'{as_of:%d.%m.%Y}')}: {_percent(values[-1])}."
    changes = sum(1 for before, after in pairwise(values) if before != after)
    years = PRIME_MONTHS // 12
    if changes == 0:
        return f"{current} היא לא השתנתה ב-{years} השנים האחרונות."
    times = "פעם אחת" if changes == 1 else f"{changes} פעמים"
    return (
        f"{current} ב-{years} השנים האחרונות נעה בין {_percent(min(values))} ל-"
        f"{_percent(max(values))} והשתנתה {times}."
    )


def _cpi_line(points: tuple[MarketPoint, ...]) -> str:
    values = [point.value for point in points]
    total = (prod((1 + value / 100 for value in values), start=Decimal(1)) - 1) * 100
    total = total.quantize(_ONE_DECIMAL, ROUND_HALF_UP)
    until = _month(points[-1].month)
    if total > 0:
        moved = f"עלה מדד המחירים לצרכן ב-{_percent(total)} בסך הכול"
    elif total < 0:
        moved = f"ירד מדד המחירים לצרכן ב-{_percent(-total)} בסך הכול"
    else:
        moved = "לא השתנה מדד המחירים לצרכן בסך הכול"
    return (
        f"ב-{CPI_MONTHS} החודשים האחרונים (עד {until}) {moved}; השינוי החודשי נע בין "
        f"{_percent(min(values))} ל-{_percent(max(values))}."
    )


def _percent(value: Decimal) -> str:
    return _figure(f"{value.normalize():f}%")


def _month(month: date) -> str:
    return _figure(f"{month:%m/%Y}")


def _figure(text: str) -> str:
    return f"{_ISOLATE_START}{text}{_ISOLATE_END}"
