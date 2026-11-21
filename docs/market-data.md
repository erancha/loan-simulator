# Market data

This document details the market data behind the loan engine's part of
[Architecture](architecture.md#the-loan-engine). The engine prices tracks over the published
series below. `loan_engine.market` fetches them, aligns them into one `MarketHistory` and keeps
the last good copy on disk.

**Contents:** [Series](#series) · [Request quirks](#request-quirks) · [Parsing](#parsing) ·
[Monthly alignment](#monthly-alignment) · [Refresh and fallback](#refresh-and-fallback) ·
[Storage](#storage)

## Series

| Series | Source | Request | Granularity |
| --- | --- | --- | --- |
| Bank of Israel rate, `MNT_RIB_BOI_D` | Bank of Israel | `.../BOI.STATISTICS/BR/1.0/MNT_RIB_BOI_D?startperiod=YYYY-MM-DD&format=csv` | daily, from 1994-01-27 |
| Consumer price index (CPI), code `120010` | Central Bureau of Statistics (CBS) | `https://api.cbs.gov.il/index/data/price?id=120010&format=json&download=false&startPeriod=MM-YYYY&PageSize=1000` | monthly, from 1994-01 |
| Average rate on new household consumer loans, `BNK_99010_LR_BIR_1893` | Bank of Israel | `.../BOI.STATISTICS/BIR/1.0/BNK_99010_LR_BIR_1893?startperiod=YYYY-MM-DD&format=csv` | monthly, from 2016-01 |

The Bank of Israel base URL is `https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow`.
The consumer-loan series excludes overdrafts and housing-secured credit and mixes fixed and
variable rates.

## Request quirks

- The Bank of Israel rejects the default library User-Agent; every request to it sends
  `Mozilla/5.0`.
- The CBS returns 10 rows per page by default. Requests pass `PageSize=1000`, which holds the whole
  history (393 months from 1994-01 to 2026-09). A response with more than one page raises an error
  instead of silently truncating the series.
- The CBS lists months newest first; the fetcher sorts them oldest first.

## Parsing

- Bank of Israel CSV: `TIME_PERIOD` and `OBS_VALUE`. The rate series has a `YYYY-MM-DD` period,
  the consumer-loan series `YYYY-MM`, read as the first of that month.
- CPI: the monthly change is the published `percent` divided by 100, as a fraction. Index levels
  are not used, because they restart at each base change (for example 108.4 in 2024-12 on the 2022
  base and 101.5 in 2025-01 on the 2024 base); `percent` is the change within one base.
- All values are `Decimal`. A value that is not a finite number, NaN and infinities included,
  fails the fetch of its series with an error naming the series and the value.

## Monthly alignment

- The daily rate is reduced to its value in effect on each first of the month: the latest daily
  value on or before that date, so weekends and holidays without a row carry the previous value.
- The history's months are those present in both the monthly rate and the CPI. The rate runs a
  month or more past the latest CPI, so the latest CPI month ends the history.
- The history's months must be consecutive: a month missing from either series inside the
  shared span fails the build with an error naming the gap, so no historical window spans a
  missing month.
- `current_boi_rate` and `rate_as_of` are the latest daily value and its date; `cpi_as_of` is the
  latest CPI month.
- `consumer_rate` and `consumer_rate_month` are the latest point of the consumer-loan series
  (fetched from 24 months before today, as only the latest value is used).
  `consumer_month_prime` is the prime rate of that month: the Bank of Israel rate in effect on its
  first day plus 1.5.

## Refresh and fallback

`refresh(store, client)` fetches all three series, builds the history and saves it; when it runs
is in [Workers' responsibilities and flows](workers.md#_refresh_daily).

If any fetch fails (an HTTP error, or a response that does not parse) or the series do not align
into a history (`series_alignment`), `refresh` logs a warning naming the failed series and the
data dates of the stored history, and returns the stored history. With nothing stored it raises
`MarketDataUnavailableError` naming the failed series, so startup fails rather than running
without data.

Every history carries its data dates (`rate_as_of`, `cpi_as_of`, `consumer_rate_month`), so each
result can show how old its inputs are.

## Storage

`SeriesStore` keeps one JSON file: decimals as strings, dates in ISO form, plus the fetch time. A
save writes a temporary file in the same directory and renames it over the target, so a reader
sees either the old file or the new one.
