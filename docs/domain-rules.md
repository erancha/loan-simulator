# Domain rules

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

The base path gives today's payment and the expected total cost. The rate is held flat at today's
value: the fixed rate, or the current Bank of Israel rate + 1.5 + the track's spread for a prime
track. The spread runs from -1.5, prime minus its whole margin, which leaves the Bank of Israel rate
itself, up to 20. A CPI-linked track is indexed by 2% a year, `(1.02)^(1/12) - 1` per month, the
middle of the Bank of Israel's 1-3% inflation target.

The base path is the engine's default scenario (`DEFAULT_SCENARIO`): the CPI rising 2% a year and
prime unchanged. `price(track, history, scenario)` builds the path of any scenario the same way.

### Scenarios

A scenario is a future the person names, held for the whole loan: `cpi_per_year`, how much the CPI
rises each year in percent (−5 to 20), and `prime_per_year`, how much prime rises each year in
percentage points (−5 to 5). A value the person does not name keeps the default. The CPI's yearly
rise is indexed monthly, `(1 + cpi_per_year/100)^(1/12) - 1`; the Bank of Israel rate, and prime
with it, moves by a twelfth of `prime_per_year` more each month from today's, floored at zero as
in a window. So a CPI rise moves a linked track, a prime rise a prime track, and a fixed unlinked
track moves with neither. A movement may instead be given as the last N years (1 to 10,
`cpi_like_last_years`, `prime_like_last_years`), and `resolved` turns it into its yearly figure
from the latest history: the CPI's compounded rise over those months, taken to a yearly rate, and
prime's change over them divided by the years, each to a hundredth. A scenario is never replayed
against the windows: `simulate_scenario` prices the scenario alone, and `simulate_loan` keeps the
base path and the windows.

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
different monetary regime. An 84-month track, the longest the engine prices, still has 37
windows.

## Policy

The limits and searches below are what the agent's term card, ceiling check and remedies rest
on. Their values are constants in `domain/assumptions.py`. The engine prices a principal of
10,000 to 10,000,000 ₪ and a term of 6 to 84 months, for every purpose; a car loan may run past
the usual 60 months, as a bridging loan does.

### The payment ceiling

The payment ceiling is the only figure the engine derives from the person's finances, and it is
optional: a person may state a ceiling instead, or give none. `domain/affordability.py` holds the
formula, and an import-linter contract keeps the loan arithmetic (`policy`, `history`,
`schedule`) from importing it. It takes two monthly figures: net fixed income, which includes
the variable income that arrives even in a weak month, and fixed expenses, which include the
payments on existing loans. The ceiling is the lower of two caps, never below 0:

- 30% of the net fixed income: the share of income a single loan payment may take.
- 50% of the net fixed income minus the fixed expenses: half of what remains after the fixed
  costs, so the other half stays for variable spending and shocks.

The result carries both caps with their shares, and names which cap applied (income share on a
tie) and whether nothing is left. For 12,000 ₪ of income and 6,000 ₪ of expenses the caps are
3,600 and 3,000, so the ceiling is 3,000 ₪. The agent hands the two caps to the model at every
call, and the first recommendation's message shows the person the calculation.

### Fits the ceiling

An option fits a ceiling when its highest recurring payment, in its worst historical window for a
variable track, is at or below the ceiling itself: there is no safety margin. A balloon is paid
once at the end, so it is not counted. Each option is judged on its own, so a fixed track may fit
a ceiling that the prime track, at its worst window's payment, passes.

### Typical tracks

Before the person has real offers, three example tracks illustrate the loan. Two are typical
tracks, what most consumer lenders (banks, credit-card companies, car financiers) offer, priced
from the Bank of Israel's published average rate on new unindexed household consumer loans, for
its latest month:

- Fixed, unlinked, at that average rate.
- Prime, unlinked, with a spread equal to that average minus the prime in effect in the same
  month (2026-08: 7.9% - 5.0% = 2.9%).

The series mixes fixed and variable rates and has no split between them, so the same average
prices both kinds. No published series covers CPI-linked consumer loans. The third example is the
kind of loan a pension, provident or study fund gives its members against their savings: fixed at
4% a year, linked to the CPI (`PENSION_FUND_RATE` in `domain/assumptions.py`). A large Israeli
pension fund publishes 3.5% or 4% plus the CPI, depending on underwriting, for up to 84 months
and up to 30% of the fund's balance; the example takes the upper end, so it never promises the
better underwriting result. It shows a person with such a fund what to ask it, and its card's
range replays the CPI history for a linked track.

All three are equal-payment (spitzer) tracks without fees, at the check's principal and term.
They are examples, which illustrate a loan before any lender has quoted one; nobody can take
them. They are saved as options only when the person asks for them. The first real offer
saved on a check, or the first offer that awaits its lender, deletes its examples, with a
recommendation that names one, and no example is saved while the check holds an offer of its loan
amount or an awaiting offer. From then on offers are compared only with each other, so no offer
is ever measured against an example. The term card's proposal and the searches below price the
two typical tracks alone, without saving them, since they are what most lenders offer; the
pension fund example is priced at the check's term, and when its worst case passes the ceiling
the card says so as for any option.

### The price of an offer

A payment that fits the ceiling says only that the person can carry it, not that the loan is a
good one, so every real offer is shown with its price, worked out in code and never by the model:

- **Interest cost**: the total paid on the base path minus the principal (`Option.interest_cost`
  in `backend/src/loan_agent/domain/models.py`), so fees and, for a CPI-linked loan, the CPI's
  rise on the base path are in it. Prime + 6% on 45,000 ₪ over 60 months, at a prime of 4.75%,
  pays 58,368 ₪ in total: about 13,368 ₪ over the principal.
- **Rate today against the market**: the rate the loan charges in its first month (`rate_today`
  in `domain/history.py`: the fixed rate, or today's prime plus the spread) against the Bank of
  Israel's average rate on new unindexed household consumer loans, the same average the typical
  tracks are priced at. An unlinked rate within 0.25 percentage points of the average is similar
  to it (`SIMILAR_RATE_POINTS` in `domain/assumptions.py`); further off it is above or below
  (`rate_against_market` in `domain/policy.py`). In the example, 10.75% is above 7.9%.
- A CPI-linked rate is on top of the CPI, so setting it against an unlinked average would compare
  unlike rates: it is stated as "4% מעל המדד", with no comparison.

`simulate_loan` returns each track's rate today and its comparison, and the average with its
month, and the agent stores them with the option's figures. An option saved before the engine
reported them has no rate line; its interest cost is still shown.

### Proposed term

The term card is a first calculation from a stated assumption, which the person tunes on the
card; a real offer later carries its own term. The agent chooses the term the same way for every
purpose, from the engine's searches in 6-month steps up to 84 months:

- While the check has no ceiling, the card assumes a first payment of 1,000 ₪
  (`FIRST_PAYMENT_TARGET` in `backend/src/loan_agent/domain/models.py`) and takes the shortest
  term at which both typical tracks' first payment is under it (`propose_term`), else 84 months.
- Once the check has a ceiling, stated or derived, it takes the shortest term at which both
  typical tracks' worst-case payments fit it (`shortest_comfortable_term`), else 84 months.

The first payment shown on the card is the higher of the two tracks' first payments at that term.
The card states which assumption it used, with its amount, and says so when even 84 months does
not keep the payment under it.

### Comparing terms

Once a check has a recommendation, the person may ask for a shorter or a longer term without
naming one, in their own words or with the "קיצור תקופה" and "הארכת תקופה" chips. The agent then
prices the recommended option at its own term and at the next two whole multiples of 6 months in
that direction (72 gives 66 and 60, or 78 and 84; 70 gives 66 and 60), and the terms card shows
each with its payment today and its worst-case payment, marked when that passes the ceiling. A
marked term stays a choice: the mark informs, and the person decides. Every row is priced on the
recommended option itself, so its figures match the recommendation's. The rows stop at 6 months,
at the longest term the option's lender allows, and, going shorter, before the first term whose
payment at today's rates is already above the ceiling. An offer whose lender fixed its term has
no other term to price. A chosen row is saved like a confirmed term card, the open offers are
priced at it, and the recommendation is made again.

### Remedies above the ceiling

When the recommended options do not fit the ceiling and no saved option for the term does, the
recommendation stands above the ceiling. When their payment at today's rates fits and only the
worst historical window passes the ceiling, the card says so ("בתוך התקרה שלך היום") with the
worst payment, and no remedy is offered: the person chose the term with that window in view. A
check with real offers is measured by its offers alone:
the remedy is the shortest term, within what each lender allows, at which an offer that leaves its
term open fits (`shortest_comfortable_offer_term`), else asking the lenders for a longer term or
borrowing less. A check with examples only gets two searches that give the person something
concrete:

- The shortest term up to 84 months at which at least one typical track fits
  (`shortest_comfortable_term` with `any_track`). For a prime track that is the payment in its
  worst historical window, so a past rate rise lengthens the term.
- When no term fits, the largest loan (`largest_comfortable_loan`), in whole 1,000 ₪ up to the
  largest principal, on which at least one typical track fits at the confirmed term, or at 84
  months while the person has confirmed none; none when even 10,000 ₪ does not. A typical track
  has no fees, so its payment grows in proportion to the principal: the search scales the
  payment at 10,000 ₪ to the ceiling, then steps down by 1,000 ₪ until a track fits, which
  absorbs the rounding of payments.

### Offers with an open term

An offer that leaves the term open ("up to 84 months") goes through the same searches with its
own rate: 6-month steps below its maximum, then the maximum itself. Without a ceiling it is the
first term whose first payment is under 1,000 ₪ (`propose_offer_term`); with one, the first that
fits it (`shortest_comfortable_offer_term`); in either case the maximum when none does. A longer
term only adds interest, so the offer is kept at that term, and `save_offer` refuses it at any
other. Each track of an offer is searched on its own, since each is saved as an option of its own.

### Reading an offer

Lenders often word an offer so that one sentence fits several loans: "פריים 6.45" may mean prime +
6.45% or 6.45% in total, and "969 ₪ קבוע" names no rate at all. The agent's model extracts only what
the person said (the lender, the amount and term the lender quoted, a stated number, the monthly
payment and the type words פריים, קבוע and צמוד); the engine's `offer_readings`
(`domain/readings.py`) prices each loan those figures may mean, and the agent's
`application/offer_reading.py` decides between them. Every reading is one equal-payment (spitzer)
track with no fee, priced on the amount and term the lender quoted, since the payment belongs to
them, and its first payment is the one of the base path. A reading whose rate falls outside what the
engine prices (a prime spread of -1.5 to 20, a fixed rate of 0% to 30%) is left out.

The candidate readings:

- **With a stated number X**: prime + X; X as the total rate today, that is prime + (X - prime),
  only when the words say פריים; fixed X, not linked; and fixed X, linked to the CPI.
- **With a payment and no number**: first the rate r at which a fixed, unlinked track of the
  quoted amount and term starts with that payment; then fixed r, not linked; prime + (r - prime
  today); and fixed r, linked to the CPI. The linked reading is marked approximate: its base path
  indexes the balance by 2% a year before the first payment, so it starts a little above the
  quoted payment at the same rate.

The rate r is found by bisection between 0% and 30%: 40 halvings of the bracket, each keeping the
half whose first payment holds the quoted payment, leave it far narrower than 0.01%, and the upper
bound is rounded half up to 0.01%. A payment below the 0% payment or above the 30% one gives no
rate and no reading.

The decision, for an offer that states a number and quotes a payment: a reading fits when its
first payment is within 1% of the quoted payment, the edge included.

- **Exactly one fits**: the offer is identified and saved as a real offer, whatever its type words
  said, since the payment is the lender's own arithmetic. It is saved on the check's loan amount at
  the quoted term, as every offer is priced on the check's amount.
- **Several fit**: the person sees those readings on a card and the offer awaits its lender.
- **None fits**: the type is not recognized and nothing is saved.

The simulator compares single loans of the check's amount and never combines lenders or tracks, so
an offer quoted for less than the check's loan is never saved by its reading, identified or not:
it awaits its lender's answer on lending the loan amount on the same terms. A yes saves its
reading, the identified one or the one chosen on the card, on the check's loan amount at the
quoted term; a no removes the offer, which stays out of the comparison. An offer quoted for the
loan amount or more is saved on the check's amount as above.

An offer with only a number or only a payment goes to the card with every reading: a number alone
has no payment to fit against, and readings priced from a payment all match it. A payment that no
rate gives leaves no reading, and the type is not recognized. On a card, פריים keeps only the prime
readings when it has some; צמוד marks the linked fixed reading as the likely one, else קבוע the
unlinked one. An offer on a card is left out of the recommendation until the person confirms one of
its readings, which is then saved as the offer.

With prime at 4.75% (a Bank of Israel rate of 3.25% plus the 1.5 margin):

- **Leumi**, 45,000 ₪ over 60 months, "פריים פלוס 6 ... 972 שח קבוע": prime + 6% starts at
  972.81 ₪; 6% in total and fixed 6% both start at 869.98 ₪, and fixed 6% linked at 871.41 ₪.
  Only the first is within 9.72 ₪ of 972 ₪, so the offer is prime + 6%, 10.75% today, though the
  words said קבוע.
- **Max**, 20,000 ₪ over 24 months, "6.45 פריים, 934 בחודש", on a check of 45,000 ₪: prime +
  6.45% starts at 933.85 ₪ on the quoted 20,000 ₪, so the offer is identified, but it waits for
  Max's answer on lending 45,000 ₪ on the same terms; saved on 45,000 ₪ it would start near
  2,100 ₪, a payment Max never quoted.
- **Max**, 20,000 ₪ over 24 months, "6.45 פריים, 934 ₪": prime + 6.45% starts at 934.01 ₪, and
  6.45% in total, the same as fixed 6.45%, at 890.47 ₪. The offer is prime + 6.45%, 11.2% today,
  saved on the check's loan of 45,000 ₪ at 24 months.
- **Avis**, 45,000 ₪ over 60 months, "969 ₪, קבוע", no rate: the payment amounts to a fixed
  10.58%, so the card shows fixed 10.58% not linked, prime + 5.83%, and about 10.58% linked, with
  the unlinked fixed reading likely because of קבוע.
