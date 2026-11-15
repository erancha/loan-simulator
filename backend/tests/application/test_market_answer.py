"""The market-data answer states the prime and the CPI exactly from the engine's figures."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from fakes import engine_fixture
from loan_agent.adapters.engine_mcp import market_series_of
from loan_agent.application.market_answer import CPI_MONTHS, PRIME_MONTHS, market_answer
from loan_agent.ports.engine import MarketPoint, MarketSeries

MARKET = market_series_of(engine_fixture("market_series"))


def months(*values: str) -> tuple[MarketPoint, ...]:
    return tuple(MarketPoint(date(2020, 1, 1), Decimal(value)) for value in values)


def flat_prime(market: MarketSeries, value: str) -> MarketSeries:
    return replace(market, prime=months(*[value] * PRIME_MONTHS))


def plain(text: str) -> str:
    """The text without the marks that keep each figure left to right."""
    return text.replace("\u2066", "").replace("\u2069", "")


def test_the_answer_states_the_prime_and_the_cpi_of_the_data() -> None:
    text, _charts = market_answer(MARKET)
    assert plain(text) == (
        "ריבית הפריים נכון ל-30.10.2026: 4.75%. ב-5 השנים האחרונות נעה בין 1.6% ל-6.25% "
        "והשתנתה 16 פעמים.\n\n"
        "ב-12 החודשים האחרונים (עד 09/2026) עלה מדד המחירים לצרכן ב-1.7% בסך הכול; השינוי "
        "החודשי נע בין -0.5% ל-1.2%."
    )


def test_each_figure_is_kept_left_to_right() -> None:
    text, _charts = market_answer(MARKET)
    assert "בין \u2066-0.5%\u2069 ל-\u20661.2%\u2069." in text
    assert "ל-\u206630.10.2026\u2069: \u20664.75%\u2069." in text


def test_the_charts_are_five_years_of_prime_and_one_year_of_cpi() -> None:
    _text, charts = market_answer(MARKET)
    assert [(chart["series"], len(chart["points"])) for chart in charts] == [
        ("prime", PRIME_MONTHS),
        ("cpi", CPI_MONTHS),
    ]
    assert charts[0]["as_of"] == "2026-10-30"
    assert charts[1]["points"][-1] == {"month": "2026-09-01", "value": "-0.5"}


def test_an_unchanged_prime_says_so() -> None:
    text, _charts = market_answer(flat_prime(MARKET, "6.00"))
    assert plain(text).startswith(
        "ריבית הפריים נכון ל-30.10.2026: 6%. היא לא השתנתה ב-5 השנים האחרונות."
    )


def test_one_change_reads_once() -> None:
    prime = months(*["5.5"] * (PRIME_MONTHS - 1), "6")
    text, _charts = market_answer(replace(MARKET, prime=prime))
    assert "והשתנתה פעם אחת." in plain(text)


def test_a_falling_cpi_reads_as_a_fall() -> None:
    text, _charts = market_answer(replace(MARKET, cpi_change=months(*["-0.1"] * CPI_MONTHS)))
    assert "ירד מדד המחירים לצרכן ב-1.2% בסך הכול" in plain(text)
