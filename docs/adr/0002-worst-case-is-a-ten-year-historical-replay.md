# 0002. The worst case replays the last ten years of rates and inflation

- Status: Accepted
- Date: 2026-10-27

## Context

The engine prices each loan track at today's rate and also under stress: it replays every
historical window as long as the loan's term, applying the rate and CPI changes of that window
to today's rate, and reports the worst window by peak recurring payment. Windows started at a
fixed 2000-01, so the worst prime window for a 48-month loan named the 2002 rate spike, a period
too remote for a borrower to take seriously, although the 2022 rise gave a worst case only
13 NIS a month lower.

## Decision

Windows start only within the last 120 months of the aligned monthly history (`HISTORY_MONTHS`
in `domain/assumptions.py`), so the span moves forward as new data arrives. The worst window is
reported with its start and end months, beside the range across all windows; a balloon due is
reported apart from the recurring payment. A term longer than the span raises
`NoHistoryWindowError`, naming the rolling span.

## Consequences

- The worst case names a period a person recalls, and the page shows which one it was.
- A long term is measured over fewer windows (a 96-month track over 25, a 48-month one over 73),
  and a term beyond the span cannot be priced at all.
- A spike older than ten years no longer counts, so the worst case is a stress test on recent
  experience, not on the full record.
