# 0010. The loan first, with an optional payment ceiling

- Status: Accepted
- Date: 2026-11-15

## Context

Every check began by collecting the person's household finances (savings, incomes, expenses,
existing loans), sized the loan from them, and recommended against a payment ceiling and a
savings cushion. ADR 0003's guardrail refused an option that borrowed less than the sized loan.
A tester's checks of 2026-11-14 showed the cost: a stated loan was dropped while the agent asked
six profile figures one by one; a sized loan above the stated one overrode it, and grew each time
the tester chose a larger down payment, since that lowered the saved savings; the tester repeated
the amount three times and left.

## Decision

- A check starts from the loan the person states, as an amount or as a price less own capital,
  with an optional purpose. The term card proposes a term (60 months for a car, otherwise the
  shortest whose first payment is under 1,000 ₪, up to 84) for the person to confirm or change.
- The payment ceiling is the only household figure, and it is optional: stated by the person, or
  derived by the engine from net fixed income and fixed expenses held by the check. There is no
  per-person profile, no cushion and no sizing; the formula sits in its own engine module, which
  the loan arithmetic may not import.
- This restates ADR 0003's guardrail. The model leads; `present_recommendation` refuses an option of
  another amount than the one the person asked for, since the amount is never sized. With a ceiling,
  it refuses an option whose worst-case recurring payment is above the full ceiling while a saved
  option for the term fits, each option judged on its own. When none fits, the person's term stands:
  the recommendation is marked above the ceiling and the model offers the remedy once, a longer term
  up to 84 months, else the largest loan that fits. Without one, the recommendation is on the loans'
  merits and recorded as unchecked. An example never beats a real offer.

## Consequences

- A person sees their loan simulated before any financial question, unless they ask for help.
- Checks of the earlier shape cannot be migrated: the migration refuses a database that holds
  checks.
- A recommendation without a ceiling carries no affordability claim, and the card says so.
