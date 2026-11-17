"""The decision between the loans an offer described in words may mean, made in code from the
engine's pricing: the quoted payment identifies the offer when exactly one reading fits it,
whatever its words say; the person chooses on a card when several fit or the offer lacks a
stated number or a payment; a stated number that fits nothing is not recognized.

- FIT_TOLERANCE: how close a reading's first payment must be to the quoted payment
- Decision, Outcome: what decide concludes, with the readings it rests on
- decide: the rule itself, with the type words narrowing a card's readings and marking the
  likely one
"""

from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from loan_agent.domain.models import Reading, ReadingKind, TypeWord
from loan_agent.ports.engine import OfferReadings

# A reading fits when its first payment is within this share of the quoted payment.
FIT_TOLERANCE = Decimal("0.01")
Outcome = Literal["identified", "awaiting", "unrecognized"]

_PRIME_KINDS: tuple[ReadingKind, ...] = ("prime_margin", "prime_total")


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    readings: tuple[Reading, ...]
    """The one identified, or the ones a card shows; empty when unrecognized."""
    likely: ReadingKind | None
    """Set only for a card, when the type words point to one of its readings."""


def decide(
    priced: OfferReadings,
    stated_rate: Decimal | None,
    monthly_payment: Decimal | None,
    type_words: Collection[TypeWord],
) -> Decision:
    if stated_rate is not None and monthly_payment is not None:
        tolerance = FIT_TOLERANCE * monthly_payment
        shown = tuple(
            reading
            for reading in priced.readings
            if abs(reading.first_payment - monthly_payment) <= tolerance
        )
        if len(shown) == 1:
            return Decision("identified", shown, None)
    else:
        shown = priced.readings
    if not shown:
        return Decision("unrecognized", (), None)
    return _card(shown, type_words)


def _card(shown: tuple[Reading, ...], type_words: Collection[TypeWord]) -> Decision:
    if "prime" in type_words:
        prime = tuple(reading for reading in shown if reading.kind in _PRIME_KINDS)
        if prime:
            shown = prime
    kinds = {reading.kind for reading in shown}
    likely: ReadingKind | None = None
    if "linked" in type_words and "fixed_linked" in kinds:
        likely = "fixed_linked"
    elif "fixed" in type_words and "fixed_unlinked" in kinds:
        likely = "fixed_unlinked"
    return Decision("awaiting", shown, likely)
