"""The decision between the engine's readings of an offer: the quoted payment decides when one
reading fits it, the card shows the readings when several fit or a number is missing, and a stated
number that fits nothing is not recognized."""

from datetime import date
from decimal import Decimal

from loan_agent.application.offer_reading import decide
from loan_agent.domain.models import Reading, ReadingKind
from loan_agent.ports.engine import OfferReadings


def priced(*readings: tuple[ReadingKind, str], payment_rate: str | None = None) -> OfferReadings:
    return OfferReadings(
        prime=Decimal("4.75"),
        rate_as_of=date(2026, 11, 15),
        payment_rate=None if payment_rate is None else Decimal(payment_rate),
        readings=tuple(
            Reading(
                kind=kind,
                track={"rate_kind": kind},
                first_payment=Decimal(first_payment),
                total_rate=Decimal("10.75"),
                approximate=False,
            )
            for kind, first_payment in readings
        ),
    )


LEUMI = priced(
    ("prime_margin", "972.81"),
    ("prime_total", "869.98"),
    ("fixed_unlinked", "869.98"),
    ("fixed_linked", "871.41"),
)
AVIS = priced(
    ("fixed_unlinked", "969.01"),
    ("prime_margin", "969.01"),
    ("fixed_linked", "970.61"),
    payment_rate="10.58",
)


def kinds(readings: tuple[Reading, ...]) -> list[str]:
    return [reading.kind for reading in readings]


def test_one_reading_that_fits_is_identified() -> None:
    decision = decide(LEUMI, Decimal(6), Decimal(972), [])

    assert decision.outcome == "identified"
    assert decision.readings == (LEUMI.readings[0],)


def test_the_payment_decides_over_words_that_contradict_it() -> None:
    decision = decide(LEUMI, Decimal(6), Decimal(972), ["fixed"])

    assert (decision.outcome, kinds(decision.readings)) == ("identified", ["prime_margin"])


def test_several_fitting_readings_are_carded() -> None:
    decision = decide(LEUMI, Decimal(6), Decimal(870), [])

    assert decision.outcome == "awaiting"
    assert kinds(decision.readings) == ["prime_total", "fixed_unlinked", "fixed_linked"]
    assert decision.likely is None


def test_a_number_that_fits_nothing_is_unrecognized() -> None:
    at_five = priced(
        ("prime_margin", "950.42"),
        ("prime_total", "848.69"),
        ("fixed_unlinked", "848.69"),
        ("fixed_linked", "850.10"),
    )

    decision = decide(at_five, Decimal(5), Decimal(972), [])

    assert (decision.outcome, decision.readings) == ("unrecognized", ())


def test_no_payment_cards_every_reading() -> None:
    decision = decide(LEUMI, Decimal("6.45"), None, [])

    assert (decision.outcome, decision.readings) == ("awaiting", LEUMI.readings)


def test_no_stated_number_cards_every_reading() -> None:
    decision = decide(AVIS, None, Decimal(969), [])

    assert (decision.outcome, decision.readings, decision.likely) == (
        "awaiting",
        AVIS.readings,
        None,
    )


def test_the_word_prime_keeps_the_prime_readings() -> None:
    decision = decide(LEUMI, Decimal("6.45"), None, ["prime"])

    assert kinds(decision.readings) == ["prime_margin", "prime_total"]


def test_the_word_prime_is_ignored_when_no_prime_reading_is_shown() -> None:
    fixed_only = priced(("fixed_unlinked", "870.00"), ("fixed_linked", "871.41"))

    decision = decide(fixed_only, Decimal(6), Decimal(870), ["prime"])

    assert kinds(decision.readings) == ["fixed_unlinked", "fixed_linked"]


def test_the_word_fixed_marks_fixed_unlinked_likely() -> None:
    decision = decide(AVIS, None, Decimal(969), ["fixed"])

    assert (decision.readings, decision.likely) == (AVIS.readings, "fixed_unlinked")


def test_the_word_linked_marks_fixed_linked_likely_over_fixed() -> None:
    decision = decide(AVIS, None, Decimal(969), ["fixed", "linked"])

    assert decision.likely == "fixed_linked"


def test_a_payment_at_the_edge_of_one_percent_fits() -> None:
    edges = priced(
        ("prime_margin", "989.99"),
        ("prime_total", "990.00"),
        ("fixed_unlinked", "1010.00"),
        ("fixed_linked", "1010.01"),
    )

    decision = decide(edges, Decimal(6), Decimal(1000), [])

    assert kinds(decision.readings) == ["prime_total", "fixed_unlinked"]


def test_no_reading_at_all_is_unrecognized() -> None:
    assert decide(priced(), None, Decimal(969), []).outcome == "unrecognized"
