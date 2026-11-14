# Calculations

This document details the formulas and policy numbers behind the loan engine's part of
[Architecture](architecture.md#the-loan-engine).

All money is `decimal.Decimal`. Internal calculations do not round; values are rounded to
agorot (0.01, ROUND_HALF_UP) only where they leave the server.

## Schedule

`schedule(track, annual_rates, monthly_inflation)` produces one row per month for one track. It
takes one nominal annual rate (percent) per month, so a flat rate, a prime path and a stressed
path all use the same code. Inflation is read only for CPI-linked tracks.

For month k of n, with m = n - k + 1 months remaining (including k), balance B at the start of
the month and r = annual rate / 1200:

- Interest: `B * r`
- Principal: `payment - interest`
- Closing balance: `B - principal`

The payment is recomputed every month from the current balance, remaining months and rate, so a
rate change takes effect in the next payment and the schedule still ends at zero.

### Methods

- Equal payments (`spitzer`): `payment = B * r / (1 - (1 + r)^-m)`; at `r = 0` it is `B / m`.
- Equal principal (`equal_principal`): `payment = B / m + B * r`; payments fall every month.
- Balloon (`balloon`): `payment = (B - L / (1 + r)^m) * r / (1 - (1 + r)^-m)`, where L is the
  balloon still owed at the end; at `r = 0` it is `(B - L) / m`. The monthly payments leave L
  outstanding, and the last month's payment also clears it.

### CPI linkage

For a linked track, in month k the balance is multiplied by `1 + inflation[k-1]` before the
payment is computed, and the balloon L is multiplied by the same factor. L therefore equals the
original balloon times the cumulative index to month k, and the final payment repays the indexed
balloon. With zero inflation the schedule equals the unlinked one.

### Fees and the last month

- The monthly fee is added to each month's payment and does not touch interest or balance.
- The one-time fee is added once to the total paid and appears in no month's payment.
- In the last month the payment also clears any remaining balance (the balloon and rounding
  residue), so the closing balance is exactly 0.

### Totals

`first_payment` is the first row's payment and `total_paid` the sum of all payments plus the
one-time fee. For a balloon track, `balloon_due` is the part of the last payment that clears the
balloon on top of that month's recurring payment: the original balloon for an unlinked track, the
indexed one for a linked track. `max_payment` is the largest recurring payment, the last one
counted without `balloon_due`, since the balloon is a planned one-off sum rather than a monthly
burden. For other tracks `balloon_due` is absent and `max_payment` is the largest payment.

## Historical replay

`simulate(track, history)` prices a track on a base path and replays it against every historical
window as long as its term. The constants live in `domain/assumptions.py`.

### Base path

The base path gives today's payment and the expected total cost. The rate is held flat at
today's value: the fixed rate, or the current Bank of Israel rate + 1.5 + the track's spread for
a prime track. A CPI-linked track is indexed by 2% a year, `(1.02)^(1/12) - 1` per month, the
middle of the Bank of Israel's 1-3% inflation target.

### Windows

A window is a run of consecutive months of history as long as the term. Windows start only
within the last 120 months of the series (`HISTORY_MONTHS`), so the period moves forward with the
data: every month in that span that still has the whole term of history after it starts one
window, and a 48-month track has 73 windows. When the term is longer than the history in that
span, `NoHistoryWindowError` names the term and the months available.

What a window moves depends on the track:

- Prime, unlinked: the rate only.
- Fixed, CPI-linked: inflation only; the rate stays fixed.
- Prime, CPI-linked: both, month by month as they moved together in the window.
- Fixed, unlinked: nothing can change, so there is no replay and no worst case.

### Changes, not levels

Month k of the window starting at month s uses the Bank of Israel rate

`max(current + (boi[s+k] - boi[s]), 0) + 1.5 + spread`

so the replay applies the window's rate **changes** to today's rate on the same schedule: if the
rate rose 4.65 points over 2022-2023, the replayed rate rises 4.65 points from today's. Replaying
levels would price a loan taken today at whatever rates a past decade happened to have, which
says nothing about the risk of today's loan. Inflation is applied as the window's actual monthly
CPI change, since a month's inflation is already a change.

A historical decrease larger than today's rate would push the replayed rate below zero; the Bank
of Israel rate is floored at 0 instead.

### Worst window and ranges

The worst window is the one with the highest peak recurring payment, the earliest one on a tie:
the peak payment is what the person must be able to pay every month. Its start and end dates are
the first and last historical months the replay took its rate changes and inflation from. Each
window also reports its own `balloon_due`, which for a linked track grows with that window's
inflation. The outcome also holds the range of peak recurring payments and of total paid across
all windows, and the number of windows.

### Why the last ten years

Both series reach back to 1994, but the risk figure has to be one a person believes. A worst
case named after a period the person lived through, such as the 2022 rate rise, is taken
seriously; one named after the early 2000s reads as a story about a different economy and is
dismissed. Ten years also keep out the 1990s, when inflation ran near 10% a year under a
different monetary regime. A 96-month track still has 25 windows.

## Policy

The bounds below are the limits the language-model agent has to respect when it talks to a
person. Their values are constants in `domain/assumptions.py`.

### Affordability

Counted income is the net fixed income plus the minimum of the variable income, in full. The
minimum is the part of the variable income that arrives even in a weak month; the average
variable income is kept in the profile but never counted, because a payment that depends on it
cannot be relied on in a lean month. The minimum is at least 0 and never above the average
variable income; a profile that breaks this is refused with an error naming both fields.

The monthly payment ceiling is the lower of two caps, minus the payments on existing loans, and
never below 0. An existing loan with 3 months or fewer left is not counted, since its payment
frees up for the new loan; the agent applies this when it saves the profile, and the profile
panel's hint states it for a figure the person enters:

- 30% of counted income: the share of income a single loan payment may take.
- 50% of counted income minus fixed expenses: half of what remains after the fixed costs, so the
  other half stays for variable spending and shocks.

The result names which cap applied (income share on a tie), whether a variable income
minimum above 0 was counted, whether existing loans were deducted, and whether nothing is left.

The minimum savings cushion is 2 months of fixed expenses; savings below it are never proposed for
the purchase.

### Loan sizing

The amount to finance is the goal price minus the savings above the cushion that are applied to
it. Savings below the cushion are untouched, and savings beyond what the goal needs are reported
as spare. Savings mean all liquid money, so money from selling an old car is part of them: it
fills the cushion before any of it goes to the purchase. The sizing does not enforce the minimum
loan amount: a small result is returned as is so the agent will be able to discuss it with the
person.

### Typical tracks

Before the person has real offers, two tracks are priced from the Bank of Israel's published
average rate on new unindexed household consumer loans, for its latest month:

- Fixed, unlinked, at that average rate.
- Prime, unlinked, with a spread equal to that average minus the prime in effect in the same
  month (2026-08: 7.9% - 5.0% = 2.9%).

Both are equal-payment (spitzer) tracks without fees. The series mixes fixed and variable rates
and has no split between them, so the same average prices both kinds. No published series covers
CPI-linked consumer loans, so there is no typical linked track; a linked track enters only as a
real offer.

### Comfortable term

The term of the typical tracks is the shortest, in 6-month steps up to the longest term priced,
at which both tracks' highest recurring payment stays within 90% of the payment ceiling. For the
prime track that is the payment in its worst historical window, so a past rate rise lengthens the
term. The 10% left over is room the worst path does not take. When no term fits, the loan is too
large for the ceiling, and the refusal names the largest loan the ceiling carries at the longest
term, to a whole 1,000 ₪, so the model can tell the person a concrete amount. The model asks the
engine for this term and passes it to the tracks.

An offer that leaves the term open ("up to 84 months") goes through the same search with its own
rate: 6-month steps below its maximum, then the maximum itself. A longer term only adds interest,
so the offer is kept at the first term that fits, or at its maximum when none does, and
`save_option` refuses it at any other term.
