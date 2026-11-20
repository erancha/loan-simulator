# Loan engine results

Structured content returned by the loan engine in mcp-server/ (commit f8bc90c), captured on
2026-10-27 from a locally run engine over its MCP endpoint. Market data is Bank of Israel data as
of that day: rate as of 2026-10-26, CPI as of 2026-09, consumer loan average as of 2026-08.

Each file holds the result of one call:

- `assess_affordability.json`: net fixed income 18000, variable 4000 (minimum 2000), fixed expenses
  9000, existing loans 800
- `simulate_loan_unlinked_prime.json`: one track, 80000 over 48 months, prime + 1.5, unlinked,
  spitzer
- `simulate_loan_linked_balloon.json`: one track, 80000 over 48 months, fixed 4.9%, CPI-linked,
  balloon 30000
- In both simulate_loan files, each track's `rate_today` and `against_consumer_rate` and the
  loan's `consumer_rate` and `consumer_rate_month` are the engine's output of 2026-11-17 over the
  same market data: the rate of month 1 in the schedule, and the consumer loan average above
- `suggest_tracks.json`: principal 80000, 48 months; its third track, the pension fund example at
  the engine's fixed rate, and the sentence its source ends with are the engine's output of
  2026-11-17, which takes nothing from market data
- `market_series.json`: prime_months 60, cpi_months 12, captured on 2026-10-30 from the engine's
  stored market data (rate as of 2026-10-30, CPI as of 2026-09); the prime ends at 2026-10 with
  today's prime, the CPI at 2026-09. Its `consumer_rate` and `consumer_rate_month` are the
  average consumer loan rate of the same market data, as the simulate_loan files above carry it
- `offer_readings.json`: principal 45000, term_months 60, monthly_payment 969, captured on
  2026-11-16 from the engine's test history in `mcp-server/tests/service/conftest.py` (Bank of
  Israel rate 3.25, rate as of 2026-10-20), not from market data
