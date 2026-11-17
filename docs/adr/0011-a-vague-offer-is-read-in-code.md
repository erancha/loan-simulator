# 0011. A vague offer is read in code

- Status: Accepted
- Date: 2026-11-16

## Context

A tester's checks of 2026-11-16 on a 45,000 ₪ car loan held offers from four lenders. Lenders
word offers so that one sentence fits several loans: "6.45 prime, 934 ₪" may be prime + 6.45% or
6.45% in total, and "969 ₪, קבוע" names no rate at all. The offer form demanded a rate, so an
offer with none could not be entered, and the model took one offer's payment for the person's
ceiling. Every offer typed carried its monthly payment, and wherever a number came with it, the
payment matched exactly one loan.

## Decision

- The model only extracts what the person said: the lender, the amount and term the lender
  quoted, a stated number, the monthly payment and the type words (פריים, קבוע, צמוד).
- Code prices each loan those figures may mean: the engine's `offer_readings` tool, on the
  quoted amount and term, and the agent's `application/offer_reading.py` decides between them.
- The payment decides: exactly one reading within 1% of the quoted payment identifies the offer,
  over words that contradict it, and it is saved on the check's loan amount; a stated number that
  fits nothing is not recognized and saves nothing.
- An offer that stays open (several fits, or no number or no payment) is stored as awaiting its
  lender, shown with its readings and the question to ask, and held out of the recommendation
  until the person confirms a reading.

## Consequences

- The engine has one more tool and the agent one more table, `awaiting_offers`, which a clone
  copies and a delete removes.
- A reading is a single track at equal monthly payments with no fee, so a fee or a balloon the
  lender adds to an offer in words is not part of it.
- The fit rule is 1% of the quoted payment, so two readings whose payments are that close both
  go to the person's card.
- A guess is never compared as if certain, and an offer that waits counts as a real offer
  everywhere but the recommendation, so the examples go once one exists.
