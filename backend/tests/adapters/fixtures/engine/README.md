# Loan engine results

Structured content returned by the loan engine in mcp-server/ (commit f8bc90c), captured on
2026-10-27 from a locally run engine over its MCP endpoint. Market data is Bank of Israel data as
of that day: rate as of 2026-10-26, CPI as of 2026-09, consumer loan average as of 2026-08.

Each file holds the result of one call:

- `assess_affordability.json`: net fixed income 18000, variable 4000 (stable), fixed expenses
  9000, existing loans 800
- `size_loan.json`: price 160000, trade-in 40000, savings 70000, cushion 30000
- `simulate_loan_unlinked_prime.json`: one track, 80000 over 48 months, prime + 1.5, unlinked,
  spitzer
- `simulate_loan_linked_balloon.json`: one track, 80000 over 48 months, fixed 4.9%, CPI-linked,
  balloon 30000
- `suggest_tracks.json`: principal 80000, 48 months
