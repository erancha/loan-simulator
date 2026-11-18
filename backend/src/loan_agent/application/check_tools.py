"""The agent's own tools for one check: the calls the model makes to save the loan, its term, its
payment ceiling and the person's finances, to ask the person a question and to present a
recommendation, with the guardrail that keeps a recommendation honest.

- ToolDeps: the ports, the clock and the id generator the tools act through
- CheckTools: set_loan, set_term, set_ceiling, update_finances, save_examples (the engine's
  example tracks for the check's term, all in one step, refused once the check holds a real offer
  of its loan amount or an awaiting offer), save_offer (each track of a real offer as an option
  of its own, removing the check's examples) and
  present_recommendation, each returning a compact key: value summary for the model and
  emitting an event for the page; ask, ask_term and ask_offer, emitting a question for the page
  and returning ASKED_RESULT, after which the turn ends; show_chart, emitting a market series
  for the page
- Reading an offer described in words: read_offer prices its readings with the engine and, by
  offer_reading's decision, saves the one its payment fits, keeps it awaiting the lender with
  the readings its card shows, or reports its type unrecognized; an offer quoted for less than
  the check's loan is never saved by its reading, but awaits the lender's answer on lending the
  loan amount on the same terms; confirm_reading saves the reading the person chose on the card,
  and answer_amount (answer_offer_amount for the model) saves the offer at the loan amount or
  drops it; READING_ON_SCREEN and DROPPED_ON_SCREEN are the results that tell the model the
  screen already showed the outcome
- The guardrail in present_recommendation: every named option borrows the loan amount; with a
  ceiling, every one's worst-case recurring payment fits it, and a refusal names the remedy to
  offer the person; the preferred option is the cheapest of its term that fits, unless the
  person said what makes a dearer one suit them
- ToolError: a refusal whose message tells the model what is wrong and what to do next
- ENGLISH_WORD, english_words: what marks text the person would see as not Hebrew, and the
  English words of a reply that the person did not write themselves
- price_text: an option's interest cost and its rate today against the market, which the save
  and recommendation results and the turn state give the model; a recommendation whose card
  holds one option alone also tells the model to evaluate it rather than recommend it
- summary, finances_figures, shekels: the key: value text the model reads, the finances' part
  of it, and an amount as the person reads it
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal, cast, get_args

from loan_agent.application.finances_saving import save_finances
from loan_agent.application.market_answer import chart_data
from loan_agent.application.offer_reading import decide
from loan_agent.domain.errors import AwaitingOfferNotFoundError, FinancesError, LoanError
from loan_agent.domain.models import (
    FIRST_PAYMENT_TARGET,
    AwaitingOffer,
    Check,
    Finances,
    LoanRequest,
    Option,
    OptionFigures,
    OptionSource,
    RateAgainstMarket,
    Reading,
    ReadingKind,
    Recommendation,
    TypeWord,
    compares_options,
)
from loan_agent.ports.engine import (
    EngineError,
    LoanEngine,
    MarketPoint,
    ProposedTerm,
    Simulation,
)
from loan_agent.ports.events import (
    CEILING_SET,
    CHART_SHOWN,
    EXAMPLES_REMOVED,
    LOAN_SET,
    OFFER_AWAITING,
    OFFER_DROPPED,
    OFFER_IDENTIFIED,
    OFFER_SETTLED,
    OFFER_UNRECOGNIZED,
    OPTION_SAVED,
    QUESTION_ASKED,
    RECOMMENDATION_PRESENTED,
    TERM_SET,
    EventSink,
)
from loan_agent.ports.repositories import (
    AwaitingOfferRepository,
    CheckRepository,
    OptionRepository,
    RecommendationRepository,
)

ChartSeries = Literal["prime", "cpi"]
_CHART_SERIES: tuple[str, ...] = get_args(ChartSeries)

# The engine's shortest and longest terms (MIN_TERM and MAX_TERM of the engine's limits), which
# the agent cannot import; the engine refuses a term outside them.
MIN_TERM = 6
MAX_TERM = 84

ASKED_RESULT = (
    "The question is on the person's screen and this turn ends here; their answer arrives as the "
    "next message."
)

READING_ON_SCREEN = (
    "The screen showed the person what this offer may mean, or that its type was not "
    "recognized, with what to ask the lender, the check's loan amount included when the offer "
    "was quoted for less. Write nothing about it."
)

DROPPED_ON_SCREEN = (
    "The screen told the person this offer does not cover the check's loan, so it does not "
    "enter the comparison, and the offer left the check; do not repeat it. Say in one line what "
    "comes next: another lender's offer, or the comparison of the offers the check holds."
)

# The page's card changes only through a recommendation, so a saved offer it does not reach would
# sit under an older one.
_COMPARE_THE_OFFER = (
    "compare this offer with the saved options and call present_recommendation in this turn; the "
    "person's card changes only through that call"
)

# The same holds for a recommendation made against another ceiling, or none.
_RECHECK_THE_RECOMMENDATION = (
    "the check's recommendation was made before this ceiling; call present_recommendation in this "
    "turn to check it against the ceiling; the person's card changes only through that call"
)

# One option alone has nothing to be ranked against, so the card evaluates it: its price is what
# tells the person whether to take it.
_ONLY_OPTION = (
    "this is the check's only option, so the card evaluates it and does not rank it: present it "
    "as the only offer so far and never call it preferred or recommended (no מועדף, מומלץ or "
    "המלצה). Give its price from preferred_price, the interest_cost and the rate_today against "
    "the market, and suggest getting another offer to compare it with"
)
_PERSON_DECIDES = (
    "Change neither the amount nor the term until the person chooses; when they keep them, the "
    "recommendation stands and the remedy is not offered again."
)


_EXAMPLES_REFUSED = (
    "this check holds a real offer, so examples are no longer saved: the check compares real "
    "offers; tell the person so in one line"
)


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class _Quote:
    """What a lender quoted for an offer described in words; lender is None until named."""

    lender: str | None
    amount: Decimal
    term_months: int | None
    stated_rate: Decimal | None
    monthly_payment: Decimal | None
    type_words: tuple[TypeWord, ...]


@dataclass(frozen=True)
class _ShorterTerm:
    """A term shorter than the preferred option's own (from_term_months) at which the option
    still fits the ceiling: its worst-case monthly payment there and the total it saves, both
    in whole shekels."""

    term_months: int
    from_term_months: int
    worst_payment: Decimal
    saving: Decimal


@dataclass(frozen=True)
class ToolDeps:
    checks: CheckRepository
    options: OptionRepository
    awaiting: AwaitingOfferRepository
    recommendations: RecommendationRepository
    engine: LoanEngine
    sink: EventSink
    clock: Callable[[], datetime]
    new_id: Callable[[], str]


class CheckTools:
    def __init__(self, user_id: str, check_id: str, deps: ToolDeps) -> None:
        self._user_id = user_id
        self._check_id = check_id
        self._deps = deps

    async def set_loan(
        self, purpose: str | None, amount: object, payment_ceiling: object | None = None
    ) -> str:
        """Saves the loan, and the payment ceiling as stated when the person named one with it,
        so a ceiling in the message that states the loan is saved before the term card proposes
        a term. Everything is checked before anything is saved."""
        if purpose is not None and not purpose.strip():
            raise ToolError("purpose is empty; omit it when the person named no purpose")
        try:
            loan = LoanRequest(purpose, _amount("amount", amount))
        except LoanError as error:
            raise ToolError(f"{error}; ask the person for the correct amount") from None
        ceiling = None if payment_ceiling is None else _ceiling(payment_ceiling)
        await self._require_priced(loan.amount)
        await self._deps.checks.set_loan(self._check_id, loan)
        data = _json_ready(asdict(loan))
        await self._deps.sink.emit(self._check_id, LOAN_SET, data)
        if ceiling is not None:
            data = {**data, **await self._save_stated_ceiling(ceiling)}
        recommendation = await self._deps.recommendations.latest(self._check_id)
        if recommendation is not None and recommendation.loan_amount != loan.amount:
            return summary(
                {
                    **data,
                    "next_step": f"the check's recommendation is for {recommendation.loan_amount}; "
                    "save options of the new amount and call present_recommendation in this turn",
                }
            )
        return summary(data)

    async def _require_priced(self, amount: Decimal) -> None:
        """The engine alone knows the principal limits it prices; asking it for the example
        tracks of the amount refuses an amount outside them, naming the limit."""
        try:
            await self._deps.engine.suggest(amount, MAX_TERM)
        except EngineError as error:
            raise ToolError(
                f"The engine refused the amount: {error}; tell the person the range this "
                "simulator prices and ask for an amount within it"
            ) from None

    async def ask_term(self, term_months: int | None) -> str:
        """With term_months None, the card proposes a term; with a number, the card shows that
        term's first payment. The question's basis tells the card where the term comes from: the
        assumption the proposed term rests on, the shorter term the recommendation suggested,
        with what it saves, or a term the person typed."""
        if term_months is not None:
            _require_term(term_months)
            if term_months == await self._last_card_term():
                raise ToolError(
                    f"The last term card already showed {term_months} months, so the person's "
                    f"answer confirms it: call set_term with {term_months}"
                )
        check = await self._check()
        loan = _require_loan(check, "ask_term")
        if term_months is None:
            proposed, basis = await self._proposed_term(check, loan)
        else:
            proposed = ProposedTerm(term_months, await self._first_payment(loan, term_months))
            basis = await self._typed_or_suggested(check, term_months)
        question = {
            "kind": "term",
            "term_months": proposed.term_months,
            "first_payment": str(proposed.first_payment),
            "basis": basis,
        }
        await self._deps.sink.emit(
            self._check_id, QUESTION_ASKED, {"question": question, "lead_in": None}
        )
        return ASKED_RESULT

    async def ask_offer(
        self,
        lender: str | None,
        tracks: Sequence[Mapping[str, object]],
        max_term_months: int | None,
    ) -> str:
        """Shows the offer form with whatever the person already said filled in. The values are
        a starting point for the boxes: the form validates what the person submits, and
        save_offer what the model saves from it. An offer with nothing missing is refused, since
        the form would only ask the person for what they already said."""
        _require_loan(await self._check(), "ask_offer")
        _require_named_lender(lender)
        if (
            lender is not None
            and max_term_months is not None
            and tracks
            and all(track["rate"] is not None for track in tracks)
        ):
            raise ToolError(
                "the offer already names its lender, every track's rate and its term, so the "
                "form has nothing to ask; save it with save_offer"
            )
        question = {
            "kind": "offer",
            "lender": lender,
            "tracks": [dict(track) for track in tracks],
            "max_term_months": max_term_months,
        }
        await self._deps.sink.emit(
            self._check_id, QUESTION_ASKED, {"question": question, "lead_in": None}
        )
        return ASKED_RESULT

    async def _typed_or_suggested(self, check: Check, term_months: int) -> dict[str, object]:
        """The basis of a card for an explicit term: the shorter term the check's recommendation
        suggests when the term is that one, so the card states what it saves; otherwise typed."""
        ceiling = check.payment_ceiling
        recommendation = await self._deps.recommendations.latest(self._check_id)
        if ceiling is not None and recommendation is not None:
            preferred = await self._deps.options.get(
                self._check_id, recommendation.preferred_option_id
            )
            shorter = await self._shorter_term(preferred, ceiling)
            if shorter is not None and shorter.term_months == term_months:
                return {
                    "kind": "shorter",
                    "amount": str(ceiling),
                    "from_term_months": shorter.from_term_months,
                    "worst_payment": str(shorter.worst_payment),
                    "saving": str(shorter.saving),
                }
        return {"kind": "typed"}

    async def _last_card_term(self) -> int | None:
        """The term of the check's latest question when it is a term card."""
        asked = await self._deps.sink.latest(self._check_id, QUESTION_ASKED)
        if asked is None:
            return None
        question = cast(Mapping[str, object], asked["question"])
        return cast(int, question["term_months"]) if question.get("kind") == "term" else None

    async def _proposed_term(
        self, check: Check, loan: LoanRequest
    ) -> tuple[ProposedTerm, dict[str, object]]:
        """The proposed term with the basis the card states for it. With a ceiling, the shortest
        term at which every lender example's worst case fits it, or the longest term when none
        does: a limit the person knows decides the term. Without one, the shortest term whose
        first payment is under the target the card assumes, or the longest when none is."""
        ceiling = check.payment_ceiling
        if ceiling is None:
            proposed = await self._deps.engine.propose_term(loan.amount, FIRST_PAYMENT_TARGET)
            fits = proposed.first_payment < FIRST_PAYMENT_TARGET
            return proposed, _term_basis("first_payment_target", FIRST_PAYMENT_TARGET, fits)
        found = await self._comfortable_term(loan.amount, ceiling, any_track=False)
        term = MAX_TERM if found is None else found
        proposed = ProposedTerm(term, await self._first_payment(loan, term))
        return proposed, _term_basis("ceiling", ceiling, found is not None)

    async def _first_payment(self, loan: LoanRequest, term_months: int) -> Decimal:
        """The higher first payment of the lender examples, as the engine's term proposal gives."""
        examples = await self._lender_examples(loan.amount, term_months)
        return max(figures.first_payment for _, figures in examples)

    async def _lender_examples(
        self, amount: Decimal, term_months: int
    ) -> list[tuple[Mapping[str, object], OptionFigures]]:
        """The engine's unlinked example tracks of the loan at the term, each with its simulated
        figures. They are what most lenders offer, so the engine's term and loan searches use
        them alone; the linked pension fund example is priced at the check's term."""
        engine = self._deps.engine
        examples = []
        for track in await engine.suggest(amount, term_months):
            if not track["cpi_linked"]:
                simulation = await engine.simulate({"tracks": [track]})
                examples.append((track, simulation.figures))
        return examples

    async def set_term(self, term_months: int) -> str:
        try:
            repriced = await self.save_term(term_months)
        except EngineError as error:
            raise ToolError(
                f"The engine refused to price the offers at {term_months} months: {error}"
            ) from None
        data: dict[str, object] = {"term_months": term_months}
        if repriced:
            data["offers_repriced"] = ", ".join(repriced)
        return summary(data)

    async def save_term(self, term_months: int) -> list[str]:
        """Saves the term and prices every offer that leaves its term open at it, up to the
        offer's maximum, so each option on the card is for the term the person is deciding on.
        All the prices are taken before anything is written, so an engine refusal saves nothing.
        Returns the ids of the offers priced again. The page's term confirmation saves through
        here too."""
        _require_term(term_months)
        _require_loan(await self._check(), "set_term")
        repriced = []
        for option in await self._deps.options.list(self._check_id):
            if option.max_term_months is None:
                continue
            (track,) = cast(list[Mapping[str, object]], option.loan["tracks"])
            term = min(term_months, option.max_term_months)
            if track["term_months"] != term:
                loan = {**option.loan, "tracks": [{**track, "term_months": term}]}
                repriced.append((option, loan, await self._deps.engine.simulate(loan)))
        await self._deps.checks.set_term(self._check_id, term_months)
        await self._deps.sink.emit(self._check_id, TERM_SET, {"term_months": term_months})
        for option, loan, simulation in repriced:
            priced = replace(option, loan=loan, summary=simulation.figures)
            await self._deps.options.replace(priced)
            await self._deps.sink.emit(
                self._check_id,
                OPTION_SAVED,
                {**_option_data(priced), "result": simulation.structured},
            )
        return [option.id for option, _, _ in repriced]

    async def set_ceiling(self, amount: object) -> str:
        """The ceiling the person states replaces any ceiling the check held."""
        return await self._with_recheck(await self._save_stated_ceiling(_ceiling(amount)))

    async def _save_stated_ceiling(self, ceiling: Decimal) -> dict[str, str]:
        await self._deps.checks.set_ceiling(self._check_id, ceiling, "stated")
        data = {"payment_ceiling": str(ceiling), "ceiling_source": "stated"}
        await self._deps.sink.emit(self._check_id, CEILING_SET, data)
        return data

    async def _with_recheck(self, data: Mapping[str, object]) -> str:
        """The summary, telling the model to recommend again when the check holds a
        recommendation, since a ceiling change re-checks it in the same turn."""
        if await self._deps.recommendations.latest(self._check_id) is None:
            return summary(data)
        return summary({**data, "next_step": _RECHECK_THE_RECOMMENDATION})

    async def update_finances(self, **fields: object) -> str:
        try:
            check = await save_finances(self._check_id, self._user_id, fields, self._deps)
        except FinancesError as error:
            raise ToolError(f"{error}; correct it and call update_finances again") from None
        except EngineError as error:
            raise ToolError(
                f"The engine refused the finances: {error}; nothing was saved, so correct them "
                "and call update_finances again"
            ) from None
        data = {
            **finances_figures(check.finances),
            "payment_ceiling": check.payment_ceiling,
            "ceiling_source": check.ceiling_source,
        }
        if check.finances.missing():
            return summary(data)
        return await self._with_recheck(data)

    async def save_examples(self) -> str:
        """Saves every example track the engine suggests for the check's loan amount and term, in
        one step and all or none, so the check never holds part of the set and the model cannot
        leave one out. An example the check already holds is kept in place of saving it again.
        Once the check holds a real offer of its loan amount, or an offer awaiting its lender, an
        example illustrates nothing the person is deciding, so they are refused."""
        check = await self._check()
        amount = _require_loan(check, "save_examples").amount
        if check.term_months is None:
            raise ToolError(
                "the check has no term yet, and the examples are priced for its term; show the "
                "term card with ask_term and save the examples once the person confirms it"
            )
        if any(
            option.source == "offer" and option.principal == amount
            for option in await self._deps.options.list(self._check_id)
        ) or await self._deps.awaiting.list(self._check_id):
            raise ToolError(_EXAMPLES_REFUSED)
        try:
            tracks = await self._deps.engine.suggest(amount, check.term_months)
        except EngineError as error:
            raise ToolError(
                f"The engine refused to suggest the examples: {error}; no example was saved"
            ) from None
        loans = [{"tracks": [track]} for track in tracks]
        saved = await self._save_options(loans, "example", None, None, None)
        return summary(
            {f"example {number}": _inline(option) for number, option in enumerate(saved, start=1)}
        )

    async def save_offer(
        self,
        tracks: Sequence[Mapping[str, object]],
        lender: str | None = None,
        offer_date: str | None = None,
        max_term_months: int | None = None,
    ) -> str:
        """Saves each track a lender offered as an option of its own, for the whole loan amount:
        the tracks of an offer are alternatives the person chooses between, and the engine
        prices a loan of one track."""
        if not tracks:
            raise ToolError("tracks is empty; list every track the offer names")
        for later, track in enumerate(tracks):
            if track in tracks[:later]:
                raise ToolError(
                    f"tracks[{later}] repeats tracks[{tracks.index(track)}]; list each track once"
                )
        loans = [{"tracks": [track]} for track in tracks]
        saved = await self._save_options(loans, "offer", lender, offer_date, max_term_months)
        lines: dict[str, object] = {
            f"track {number}": _inline(option) for number, option in enumerate(saved, start=1)
        }
        return summary({**lines, "next_step": _COMPARE_THE_OFFER})

    async def read_offer(
        self,
        lender: str | None,
        amount: object | None,
        term_months: int | None,
        stated_rate: object | None,
        monthly_payment: object | None,
        type_words: Sequence[TypeWord],
        awaiting_id: str | None,
    ) -> str:
        """Reads an offer described in words back as the loan it means. With awaiting_id it
        starts from that awaiting offer: an argument given replaces its value and the type words
        add to its own. The readings are priced on the amount and term the lender quoted, since
        the payment belongs to them; a saved offer borrows the check's loan amount. Everything is
        checked before anything is saved."""
        check = await self._check()
        loan = _require_loan(check, "read_offer")
        stored = None if awaiting_id is None else await self._awaiting_offer(awaiting_id)
        base = (
            _Quote(None, loan.amount, check.term_months, None, None, ())
            if stored is None
            else _quote_of(stored)
        )
        quote = _Quote(
            base.lender if lender is None else lender,
            base.amount if amount is None else _amount("amount", amount),
            base.term_months if term_months is None else term_months,
            base.stated_rate if stated_rate is None else _amount("stated_rate", stated_rate),
            (
                base.monthly_payment
                if monthly_payment is None
                else _amount("monthly_payment", monthly_payment)
            ),
            tuple(dict.fromkeys([*base.type_words, *type_words])),
        )
        _require_named_lender(quote.lender)
        if quote.lender is None:
            raise ToolError(
                "lender is missing; ask the person who made the offer, then call read_offer again"
            )
        if quote.term_months is None:
            raise ToolError(
                "the offer's term is unknown and the check has none; ask the person for the "
                "number of months, then call read_offer again"
            )
        if quote.stated_rate is None and quote.monthly_payment is None:
            raise ToolError(
                "the offer states neither a number nor a monthly payment, so nothing can be read "
                "back; open the offer form with ask_offer"
            )
        if stored is None:
            await self._refuse_awaiting_again(quote)
        try:
            priced = await self._deps.engine.offer_readings(
                quote.amount,
                quote.term_months,
                quote.stated_rate,
                quote.monthly_payment,
                prime_total="prime" in quote.type_words,
            )
        except EngineError as error:
            raise ToolError(
                f"The engine refused the offer: {error}; correct it and call read_offer again"
            ) from None
        decision = decide(priced, quote.stated_rate, quote.monthly_payment, quote.type_words)
        if decision.outcome == "unrecognized":
            await self._deps.sink.emit(self._check_id, OFFER_UNRECOGNIZED, {"lender": quote.lender})
            return READING_ON_SCREEN
        # The simulator compares single loans of the check's amount, and a lender who quoted less
        # may not lend it, so a short offer waits for the lender's answer even when identified.
        if decision.outcome == "awaiting" or quote.amount < loan.amount:
            offer = AwaitingOffer(
                id=self._deps.new_id() if stored is None else stored.id,
                check_id=self._check_id,
                lender=quote.lender,
                amount=quote.amount,
                term_months=quote.term_months,
                stated_rate=quote.stated_rate,
                monthly_payment=quote.monthly_payment,
                payment_rate=priced.payment_rate,
                type_words=quote.type_words,
                readings=decision.readings,
                likely=decision.likely,
                prime=priced.prime,
                rate_as_of=priced.rate_as_of,
                created_at=self._deps.clock() if stored is None else stored.created_at,
            )
            await self._deps.awaiting.save(offer)
            await self._remove_examples(await self._deps.options.list(self._check_id))
            await self._deps.sink.emit(
                self._check_id,
                OFFER_AWAITING,
                {**_awaiting_data(offer), "identified": decision.outcome == "identified"},
            )
            return READING_ON_SCREEN
        (reading,) = decision.readings
        assert quote.monthly_payment is not None, "only a quoted payment identifies an offer"
        saved = await self._save_reading(reading, quote.lender, quote.term_months)
        if stored is not None:
            await self._settle(stored.id, reading)
        await self._deps.sink.emit(
            self._check_id,
            OFFER_IDENTIFIED,
            {
                "option_id": saved["option_id"],
                "lender": quote.lender,
                "reading": reading.to_json(),
                "prime": str(priced.prime),
                "rate_as_of": priced.rate_as_of.isoformat(),
                "monthly_payment": str(quote.monthly_payment),
                "quoted_amount": str(quote.amount),
                "loan_amount": str(loan.amount),
            },
        )
        return summary(
            {
                **saved,
                "next_step": "the person's screen shows how the offer was identified, so do not "
                f"repeat it; {_COMPARE_THE_OFFER}",
            }
        )

    async def confirm_reading(self, awaiting_id: str, kind: ReadingKind) -> None:
        """Saves the reading the person chose on an awaiting offer's card as the offer; an offer
        quoted for less than the check's loan is refused, since it is saved only through its
        amount question. AwaitingOfferNotFoundError propagates for an offer the check does not
        hold."""
        offer = await self._deps.awaiting.get(self._check_id, awaiting_id)
        loan = _require_loan(await self._check(), "the offer")
        if offer.amount < loan.amount:
            raise ToolError(
                f"awaiting offer {awaiting_id} is quoted for {offer.amount}, less than the check's "
                f"loan amount of {loan.amount}; answer its amount question instead"
            )
        reading = _held_reading(offer, kind)
        await self._save_reading(reading, offer.lender, offer.term_months)
        await self._settle(offer.id, reading)

    async def answer_amount(self, awaiting_id: str, covers: bool, kind: ReadingKind | None) -> str:
        """The lender's answer to an offer quoted for less than the check's loan: covers saves
        its reading, the chosen kind or the only one it holds, as an offer of the loan amount on
        the same terms; otherwise the offer leaves the check. AwaitingOfferNotFoundError
        propagates for an offer the check does not hold."""
        offer = await self._deps.awaiting.get(self._check_id, awaiting_id)
        loan = _require_loan(await self._check(), "the offer")
        if offer.amount >= loan.amount:
            raise ToolError(
                f"awaiting offer {awaiting_id} is quoted for {offer.amount}, the check's loan "
                f"amount of {loan.amount} or more, so it has no amount question; a later detail "
                "of it goes to read_offer with its awaiting_id"
            )
        if not covers:
            await self._deps.awaiting.remove(self._check_id, awaiting_id)
            await self._deps.sink.emit(
                self._check_id,
                OFFER_DROPPED,
                {
                    "awaiting_id": awaiting_id,
                    "lender": offer.lender,
                    "quoted_amount": str(offer.amount),
                    "loan_amount": str(loan.amount),
                },
            )
            return DROPPED_ON_SCREEN
        if kind is None:
            if len(offer.readings) > 1:
                held = ", ".join(reading.kind for reading in offer.readings)
                raise ToolError(
                    f"awaiting offer {awaiting_id} still leaves its type open between {held}; "
                    "pass the reading the person said the lender meant, or ask them"
                )
            (reading,) = offer.readings
        else:
            reading = _held_reading(offer, kind)
        saved = await self._save_reading(reading, offer.lender, offer.term_months)
        await self._settle(offer.id, reading)
        return summary({**saved, "next_step": _COMPARE_THE_OFFER})

    async def answer_offer_amount(
        self, awaiting_id: str, covers: bool, kind: ReadingKind | None
    ) -> str:
        """answer_amount for the model, whose unknown awaiting id is a refusal it can act on."""
        await self._awaiting_offer(awaiting_id)
        return await self.answer_amount(awaiting_id, covers, kind)

    async def _awaiting_offer(self, awaiting_id: str) -> AwaitingOffer:
        try:
            return await self._deps.awaiting.get(self._check_id, awaiting_id)
        except AwaitingOfferNotFoundError:
            raise ToolError(
                f"this check holds no awaiting offer {awaiting_id!r}; use an id from "
                "awaiting_offers, or omit awaiting_id for a new offer"
            ) from None

    async def _refuse_awaiting_again(self, quote: _Quote) -> None:
        """Refuses a new offer equal to an awaiting one in all it quotes but its type words,
        which a later message about the same offer adds."""
        wordless = replace(quote, type_words=())
        for offer in await self._deps.awaiting.list(self._check_id):
            if replace(_quote_of(offer), type_words=()) == wordless:
                raise ToolError(
                    f"this offer is already awaiting its lender as {offer.id}; to change it, call "
                    f"read_offer with awaiting_id {offer.id}"
                )

    async def _save_reading(
        self, reading: Reading, lender: str, term_months: int
    ) -> dict[str, object]:
        """Saves the reading's track as a real offer of the check's loan amount at the quoted
        term, removing the check's examples."""
        amount = _require_loan(await self._check(), "the offer").amount
        track = {**reading.track, "principal": str(amount), "term_months": term_months}
        (saved,) = await self._save_options([{"tracks": [track]}], "offer", lender, None, None)
        return saved

    async def _settle(self, awaiting_id: str, reading: Reading) -> None:
        await self._deps.awaiting.remove(self._check_id, awaiting_id)
        await self._deps.sink.emit(
            self._check_id,
            OFFER_SETTLED,
            {"awaiting_id": awaiting_id, "kind": reading.kind, "reading": reading.to_json()},
        )

    async def _save_options(
        self,
        loans: Sequence[Mapping[str, object]],
        source: OptionSource,
        lender: str | None,
        offer_date: str | None,
        max_term_months: int | None,
    ) -> list[dict[str, object]]:
        """Prices every loan before saving any, so a refusal of one saves none of them. Each is
        refused when it borrows other than the check's loan amount, when an offer that leaves
        its term open is not at the term _offer_term gives, and, for an offer, when an option of
        the same terms and figures is already saved; an example already saved is kept in place
        of the new one, since the model does not choose the examples. Returns each option's id,
        figures and comparisons with the options of its term, an example's after its track."""
        tool = "save_offer" if source == "offer" else "save_examples"
        _require_named_lender(lender)
        offered = None if offer_date is None else _offer_date(offer_date)
        check = await self._check()
        requested = _require_loan(check, tool)
        kept = await self._deps.options.list(self._check_id)
        priced: list[tuple[Option, Simulation]] = []
        for index, loan in enumerate(loans):
            where = f"tracks[{index}]: " if source == "offer" else f"example {index + 1}: "
            try:
                simulation = await self._deps.engine.simulate(loan)
            except EngineError as error:
                remedy = (
                    f"correct it and call {tool} again"
                    if source == "offer"
                    else "no example was saved"
                )
                raise ToolError(f"{where}The engine refused the loan: {error}; {remedy}") from None
            principal = _principal(loan)
            if principal != requested.amount:
                raise ToolError(
                    f"{where}this loan borrows {principal}, not the check's loan amount of "
                    f"{requested.amount}; save it with a principal of {requested.amount}. If the "
                    "person wants another amount, call set_loan first"
                )
            if max_term_months is not None:
                term = await self._offer_term(check, loan, max_term_months)
                (track,) = cast(list[Mapping[str, object]], loan["tracks"])
                if track["term_months"] != term:
                    raise ToolError(
                        f"{where}this offer allows up to {max_term_months} months and the term "
                        f"to save is {term}; save it with term_months {term}. If the person "
                        "chose this term themselves, omit max_term_months"
                    )
            option = Option(
                id=self._deps.new_id(),
                check_id=self._check_id,
                loan=loan,
                source=source,
                lender=lender,
                offer_date=offered,
                max_term_months=max_term_months,
                summary=simulation.figures,
                created_at=self._deps.clock(),
            )
            same = next((existing for existing in kept if _same_option(existing, option)), None)
            if same is not None and source == "offer":
                raise ToolError(
                    f"{where}this option is already saved as option {same.id}, with the "
                    "same figures; use that option rather than saving it again"
                )
            priced.append((option if same is None else same, simulation))
        for option, simulation in priced:
            if option in kept:
                continue
            await self._deps.options.add(option)
            await self._deps.sink.emit(
                self._check_id,
                OPTION_SAVED,
                {**_option_data(option), "result": simulation.structured},
            )
        if source == "offer":
            await self._remove_examples(kept)
        every = await self._deps.options.list(self._check_id)
        saved = []
        for option, _ in priced:
            figures = {
                **({"track": track_text(option)} if source == "example" else {}),
                "option_id": option.id,
                **_money_figures(option),
                "price": price_text(option),
            }
            comparisons = [
                _comparison(option, other)
                for other in every
                if other.id != option.id and _terms(other) == _terms(option)
            ]
            if comparisons:
                figures["compared"] = "; ".join(comparisons)
            saved.append(figures)
        return saved

    async def _remove_examples(self, options: Iterable[Option]) -> None:
        """A real offer replaces the check's examples: they leave its options, and a
        recommendation that names one leaves with them, so no comparison, recommendation or
        remedy measures an offer against an example. The recommendation goes first, so a
        failure between the two never leaves it naming a removed option."""
        removed = [option.id for option in options if option.source == "example"]
        if not removed:
            return
        recommendation = await self._deps.recommendations.latest(self._check_id)
        names_removed = recommendation is not None and any(
            option_id in removed
            for option_id in (
                recommendation.preferred_option_id,
                recommendation.alternative_option_id,
            )
        )
        if names_removed:
            await self._deps.recommendations.remove(self._check_id)
        await self._deps.options.remove(self._check_id, removed)
        await self._deps.sink.emit(
            self._check_id,
            EXAMPLES_REMOVED,
            {"option_ids": removed, "recommendation_removed": names_removed},
        )

    async def _offer_term(
        self, check: Check, loan: Mapping[str, object], max_term_months: int
    ) -> int:
        """An offer that leaves the term open is priced at the check's confirmed term, or at the
        offer's maximum when that is shorter. Before a term is confirmed it takes the term the
        engine's search over its own track gives: without a ceiling the shortest whose first
        payment is under the target, with one the shortest that fits it, else the longest. The
        simulation already refused a loan of several tracks."""
        if check.term_months is not None:
            return min(check.term_months, max_term_months)
        ceiling = check.payment_ceiling
        (track,) = cast(list[Mapping[str, object]], loan["tracks"])
        longest = {**track, "term_months": max_term_months}
        engine = self._deps.engine
        try:
            if ceiling is None:
                proposed = await engine.propose_offer_term(longest, FIRST_PAYMENT_TARGET)
                term = proposed.term_months
            elif ceiling == 0:
                # No term fits a zero ceiling, and the engine's search takes a positive one.
                term = max_term_months
            else:
                term = (await engine.offer_term(longest, ceiling)).term_months
        except EngineError as error:
            raise ToolError(
                f"The engine refused the offer: {error}; correct it and call save_offer again"
            ) from None
        return term

    async def ask(self, question: Mapping[str, object], lead_in: str | None) -> str:
        choices = question["choices"]
        assert choices is None or isinstance(choices, list)
        _require_hebrew("lead_in", lead_in)
        _require_hebrew("text", question["text"])
        for choice in choices or []:
            _require_hebrew("choices", choice)
        if (
            question["offer_clone"]
            and await self._deps.recommendations.latest(self._check_id) is None
        ):
            raise ToolError(
                "offer_clone is for a change to a recommendation this check has; there is none "
                "yet, so do what the person asked in this check"
            )
        field = question["field"]
        known = _known_fields(await self._check())
        if field in known:
            raise ToolError(
                f"{field} is already known: {_summary_value(known[field])}; do not ask for it again"
            )
        await self._deps.sink.emit(
            self._check_id, QUESTION_ASKED, {"question": question, "lead_in": lead_in}
        )
        return ASKED_RESULT

    async def show_chart(self, series: str, months: int) -> str:
        if series not in _CHART_SERIES:
            raise ToolError(f"series must be one of {', '.join(_CHART_SERIES)}, not {series!r}")
        try:
            market = await self._deps.engine.market_series(months)
        except EngineError as error:
            raise ToolError(f"{error}; correct the months and call show_chart again") from None
        points: tuple[MarketPoint, ...]
        if series == "prime":
            points, as_of = market.prime, market.rate_as_of
        else:
            points, as_of = market.cpi_change, market.cpi_as_of
        await self._deps.sink.emit(self._check_id, CHART_SHOWN, chart_data(series, points, as_of))
        return (
            f"The {series} chart of {len(points)} months, {points[0].month:%Y-%m} to "
            f"{points[-1].month:%Y-%m}, is on the person's screen under its own title; do not "
            "list its values again"
        )

    async def present_recommendation(
        self,
        preferred_option_id: str,
        reasoning: str,
        alternative_option_id: str | None = None,
        person_preference: str | None = None,
    ) -> str:
        """Without a ceiling the recommendation is on the merits and recorded unchecked; with
        one, it is checked against it. The preferred option is the cheapest in total of those
        of its term that fit, unless person_preference holds what the person said
        that makes a dearer one suit them. Only options for the check's term count: an example of
        another term is refused, and offers count at any term, since the term's save prices them
        at it. A named option above the ceiling is refused while a saved option for the term
        fits; when none does, the person's term stands, so the recommendation is presented above
        the ceiling and its result names the remedy for the model to offer."""
        check = await self._check()
        loan = _require_loan(check, "a recommendation")
        if not reasoning.strip():
            raise ToolError("reasoning is empty; explain why the preferred option fits the person")
        named_ids = ["option_id", preferred_option_id, *filter(None, [alternative_option_id])]
        if any(name in reasoning for name in named_ids):
            raise ToolError(
                "reasoning names an option by its id; the person sees it, so name the option by "
                "its track in Hebrew (for example the prime track or the fixed track)"
            )
        _require_hebrew("reasoning", reasoning)
        if alternative_option_id == preferred_option_id:
            raise ToolError("alternative_option_id must differ from preferred_option_id")
        preferred = await self._option("preferred_option_id", preferred_option_id)
        alternative = (
            None
            if alternative_option_id is None
            else await self._option("alternative_option_id", alternative_option_id)
        )
        named = [preferred] if alternative is None else [preferred, alternative]
        for option in named:
            principal = option.principal
            if principal != loan.amount:
                raise ToolError(
                    f"option {option.id} borrows {principal}, not the check's loan amount of "
                    f"{loan.amount}; recommend options of the loan amount, saving them with "
                    "save_examples or save_offer first"
                )
        for option in named:
            if not option.for_term(check.term_months):
                raise ToolError(
                    f"option {option.id} is an example for another term than the check's "
                    f"{check.term_months} months; recommend options for the check's term"
                )
        options = [
            option
            for option in await self._deps.options.list(self._check_id)
            if option.principal == loan.amount and option.for_term(check.term_months)
        ]
        ceiling = check.payment_ceiling
        above_ceiling = None
        if ceiling is not None and not all(_fits(option, ceiling) for option in named):
            above_ceiling = await self._above_ceiling(
                check, loan, ceiling, preferred, alternative, options
            )
        if person_preference is not None and not person_preference.strip():
            raise ToolError(
                "person_preference is empty; omit it, or give what the person said that makes "
                "the preferred option suit them"
            )
        if above_ceiling is None and person_preference is None:
            _require_the_cheapest(preferred, options, ceiling)
        shorter = (
            None
            if ceiling is None or above_ceiling is not None
            else await self._shorter_term(preferred, ceiling)
        )

        recommendation = Recommendation(
            check_id=self._check_id,
            preferred_option_id=preferred.id,
            alternative_option_id=alternative_option_id,
            reasoning=reasoning,
            loan_amount=loan.amount,
            payment_ceiling=ceiling,
            created_at=self._deps.clock(),
        )
        await self._deps.recommendations.save(recommendation)
        await self._deps.sink.emit(
            self._check_id,
            RECOMMENDATION_PRESENTED,
            {
                "loan_amount": str(loan.amount),
                "payment_ceiling": _json_value(ceiling),
                "ceiling_source": check.ceiling_source,
                "checked": recommendation.checked,
                "preferred": _option_data(preferred),
                "alternative": None if alternative is None else _option_data(alternative),
                "reasoning": reasoning,
            },
        )
        data: dict[str, object] = {
            "recommendation": "presented",
            "preferred_option_id": preferred.id,
            "alternative_option_id": alternative_option_id,
            "loan_amount": loan.amount,
            "payment_ceiling": ceiling,
            "checked": recommendation.checked,
        }
        data["preferred_figures"] = _figures(preferred)
        data["preferred_price"] = price_text(preferred)
        if alternative is not None:
            data["alternative_figures"] = _figures(alternative)
            data["alternative_price"] = price_text(alternative)
        all_options = await self._deps.options.list(self._check_id)
        if not compares_options(all_options, [option.id for option in named], check.term_months):
            data["only_option"] = _ONLY_OPTION
        if ceiling is not None and above_ceiling is None:
            data["preferred_ceiling_margin"] = _margin(preferred, ceiling)
            if alternative is not None:
                data["alternative_ceiling_margin"] = _margin(alternative, ceiling)
        if above_ceiling is not None:
            data["next_step"] = above_ceiling
        elif shorter is not None:
            data["next_step"] = _shorter_term_step(shorter)
        return summary(data)

    async def _shorter_term(self, preferred: Option, ceiling: Decimal) -> _ShorterTerm | None:
        """When the preferred option fits the ceiling and its term may move (an example, or an
        offer that leaves its term open), the shortest term at which its track still fits, by
        the engine's offer search, with the interest it saves; None when no shorter term fits."""
        if preferred.source == "offer" and preferred.max_term_months is None:
            return None
        (track,) = cast(list[Mapping[str, object]], preferred.loan["tracks"])
        from_term = cast(int, track["term_months"])
        found = await self._deps.engine.offer_term(track, ceiling)
        if not found.comfortable or found.term_months >= from_term:
            return None
        shorter = {**track, "term_months": found.term_months}
        figures = (await self._deps.engine.simulate({"tracks": [shorter]})).figures
        return _ShorterTerm(
            term_months=found.term_months,
            from_term_months=from_term,
            worst_payment=figures.risk_payment.quantize(Decimal(1)),
            saving=(preferred.summary.total_paid - figures.total_paid).quantize(Decimal(1)),
        )

    async def _above_ceiling(
        self,
        check: Check,
        loan: LoanRequest,
        ceiling: Decimal,
        preferred: Option,
        alternative: Option | None,
        options: list[Option],
    ) -> str:
        """Called when a named option is above the ceiling. Refuses while a saved option for the
        term fits, saying which argument to change: the preferred option, or only the
        alternative when the preferred one fits. Otherwise returns what the presented
        recommendation's result tells the model."""
        named = [("preferred", preferred), *([("alternative", alternative)] if alternative else [])]
        payments = "; ".join(
            f"the {role} option {option.id} has a worst-case monthly payment of "
            f"{option.summary.risk_payment}, above the payment_ceiling of {ceiling}"
            for role, option in named
            if not _fits(option, ceiling)
        )
        fitting = [option for option in options if _fits(option, ceiling)]
        if not fitting:
            return (
                f"{payments}, and no saved option for the term fits, so the card marks the "
                "recommendation above the ceiling; say so in one sentence with both payments. "
                + await self._remedy(check, loan, ceiling, options)
            )
        if _fits(preferred, ceiling):
            others = [option.id for option in fitting if option.id != preferred.id]
            raise ToolError(
                f"{payments}. The preferred option fits and stands: call present_recommendation "
                f"again with preferred_option_id {preferred.id} and without "
                "alternative_option_id"
                + (f", or with an alternative that fits: {', '.join(others)}" if others else "")
            )
        raise ToolError(
            f"{payments}; "
            + "; ".join(
                f"option {option.id} fits with a worst-case monthly payment of "
                f"{option.summary.risk_payment}"
                for option in fitting
            )
            + "; name an option that fits as preferred_option_id, and no alternative above the "
            "ceiling"
        )

    async def _remedy(
        self, check: Check, loan: LoanRequest, ceiling: Decimal, options: list[Option]
    ) -> str:
        """What the model offers the person when no saved option for the term fits the ceiling.
        A check with real offers is measured by its offers alone. Without one, in order: the
        shortest term up to MAX_TERM at which a lender example fits, naming the tracks that do;
        the largest loan that fits at the confirmed term, or at MAX_TERM when the person
        confirmed none; that no loan fits."""
        offers = [option for option in options if option.source == "offer"]
        if offers:
            return await self._offer_remedy(offers, ceiling)
        term = await self._comfortable_term(loan.amount, ceiling, any_track=True)
        if term is not None:
            tracks = [
                f"the {track['rate_kind']} track, with a worst-case monthly payment of "
                f"{figures.risk_payment},"
                for track, figures in await self._lender_examples(loan.amount, term)
                if figures.risk_payment <= ceiling
            ]
            assert tracks, "the engine's term search found a term at which a lender example fits"
            return (
                f"At {term} months {' and '.join(tracks)} fits the ceiling: offer the person that "
                "term once, and once they choose it call set_term, save that option and "
                f"recommend again. {_PERSON_DECIDES}"
            )
        confirmed = MAX_TERM if check.term_months is None else check.term_months
        largest = await self._largest_loan(ceiling, confirmed)
        if largest is not None:
            return (
                f"no term up to {MAX_TERM} months fits a loan of {loan.amount}; the largest loan "
                f"that fits at {confirmed} months is {largest}. Tell the person and ask whether to "
                f"borrow less or put in more own capital. {_PERSON_DECIDES}"
            )
        return (
            f"no loan the simulator prices fits a payment_ceiling of {ceiling}, at any term; "
            f"tell the person. {_PERSON_DECIDES}"
        )

    # The engine's ceiling searches take a positive ceiling. A zero ceiling, which finances with no
    # room for a payment give, fits no loan at any term.

    async def _comfortable_term(
        self, amount: Decimal, ceiling: Decimal, *, any_track: bool
    ) -> int | None:
        if ceiling == 0:
            return None
        return await self._deps.engine.comfortable_term(amount, ceiling, any_track=any_track)

    async def _largest_loan(self, ceiling: Decimal, term_months: int) -> Decimal | None:
        if ceiling == 0:
            return None
        return await self._deps.engine.largest_loan(ceiling, term_months)

    async def _offer_remedy(self, offers: list[Option], ceiling: Decimal) -> str:
        """The shortest term, within what each offer allows, at which an offer that leaves its
        term open fits the ceiling, naming the offers that fit there; else that no offer fits at
        any term it allows."""
        fitting: list[tuple[int, Option]] = []
        for offer in offers:
            if offer.max_term_months is None or ceiling == 0:
                continue
            (track,) = cast(list[Mapping[str, object]], offer.loan["tracks"])
            longest = {**track, "term_months": offer.max_term_months}
            found = await self._deps.engine.offer_term(longest, ceiling)
            if found.comfortable:
                fitting.append((found.term_months, offer))
        if fitting:
            term = min(months for months, _ in fitting)
            named = " and ".join(
                f"option {offer.id}" for months, offer in fitting if months == term
            )
            return (
                f"At {term} months {named} fits the ceiling, within the term its lender allows: "
                "offer the person that term once, and once they choose it call set_term, which "
                f"prices the open offers at it, and recommend again. {_PERSON_DECIDES}"
            )
        return (
            "no saved offer fits the ceiling at any term its lender allows; tell the person, and "
            f"suggest asking the lenders for a longer term or borrowing less. {_PERSON_DECIDES}"
        )

    async def _check(self) -> Check:
        return await self._deps.checks.get(self._user_id, self._check_id)

    async def _option(self, argument: str, option_id: str) -> Option:
        try:
            return await self._deps.options.get(self._check_id, option_id)
        except KeyError:
            raise ToolError(
                f"{argument}: this check has no option {option_id!r}; use an option_id that "
                "save_examples or save_offer returned, or one of the state message's offers"
            ) from None


def _require_loan(check: Check, needed_by: str) -> LoanRequest:
    if check.loan is None:
        raise ToolError(
            f"{needed_by} needs the loan; ask the person for the amount and call set_loan first"
        )
    return check.loan


def _held_reading(offer: AwaitingOffer, kind: ReadingKind) -> Reading:
    chosen = [reading for reading in offer.readings if reading.kind == kind]
    if not chosen:
        held = ", ".join(reading.kind for reading in offer.readings)
        raise ToolError(f"awaiting offer {offer.id} has no {kind} reading; choose one of {held}")
    (reading,) = chosen
    return reading


# The words for "a lender" in the person's own sentences, which a model can take for a name.
_GENERIC_LENDERS = frozenset({"גוף מלווה", "הגוף המלווה", "מלווה", "המלווה"})


def _require_named_lender(lender: str | None) -> None:
    """Refuses a lender that is the word for a lender rather than its name, so no offer is
    saved or awaits under one of _GENERIC_LENDERS."""
    if lender is not None and lender.strip() in _GENERIC_LENDERS:
        raise ToolError(
            f"{lender!r} means 'a lender', not its name; use the name the person gave (in the "
            "offer form's line it follows 'הגוף המלווה:'), or ask the person for it"
        )


def _quote_of(offer: AwaitingOffer) -> _Quote:
    return _Quote(
        offer.lender,
        offer.amount,
        offer.term_months,
        offer.stated_rate,
        offer.monthly_payment,
        offer.type_words,
    )


def _awaiting_data(offer: AwaitingOffer) -> dict[str, object]:
    return {
        "awaiting_id": offer.id,
        "lender": offer.lender,
        "amount": str(offer.amount),
        "term_months": offer.term_months,
        "monthly_payment": _json_value(offer.monthly_payment),
        "payment_rate": _json_value(offer.payment_rate),
        "type_words": list(offer.type_words),
        "readings": [reading.to_json() for reading in offer.readings],
        "likely": offer.likely,
        "prime": str(offer.prime),
        "rate_as_of": offer.rate_as_of.isoformat(),
    }


def _term_basis(
    kind: Literal["first_payment_target", "ceiling"], amount: Decimal, fits: bool
) -> dict[str, object]:
    """How the term card's proposed term was chosen: the shortest term whose payment stays under
    amount, the first payment the card assumes or the check's ceiling; fits is False when even
    the longest term does not."""
    return {"kind": kind, "amount": str(amount), "fits": fits}


def _require_term(term_months: int) -> None:
    if not MIN_TERM <= term_months <= MAX_TERM:
        raise ToolError(
            f"term_months must be between {MIN_TERM} and {MAX_TERM}, the terms the simulator "
            f"prices, not {term_months}; ask the person for a term in that range"
        )


def _known_fields(check: Check) -> dict[str, object]:
    """The question fields the check already holds a value for."""
    known: dict[str, object] = {
        name: value for name, value in asdict(check.finances).items() if value is not None
    }
    if check.loan is not None:
        known["amount"] = check.loan.amount
        if check.loan.purpose is not None:
            known["purpose"] = check.loan.purpose
    if check.payment_ceiling is not None:
        known["payment_ceiling"] = check.payment_ceiling
    return known


def _fits(option: Option, ceiling: Decimal) -> bool:
    """A balloon is paid once at the end, so the test reads the recurring payment only."""
    return option.summary.risk_payment <= ceiling


# The person reads Hebrew only, while the instructions and the tools' results the model reads name
# tools and fields in English, and such a word can slip into text the person sees.
ENGLISH_WORD = re.compile(r"[A-Za-z]{2,}")


def _require_the_cheapest(
    preferred: Option, options: list[Option], ceiling: Decimal | None
) -> None:
    """Refuses a preferred option that costs more in total than another of its term that fits
    the ceiling, or any such option while the check has none, naming the cheapest."""
    cheaper = [
        option
        for option in options
        if _terms(option) == _terms(preferred)
        and (ceiling is None or _fits(option, ceiling))
        and option.summary.total_paid < preferred.summary.total_paid
    ]
    if cheaper:
        cheapest = min(cheaper, key=lambda option: option.summary.total_paid)
        saving = (preferred.summary.total_paid - cheapest.summary.total_paid).quantize(Decimal(1))
        raise ToolError(
            f"option {cheapest.id} costs {saving} less in total than the preferred option"
            f"{'' if ceiling is None else ' and fits the ceiling'}; prefer it and keep this one as "
            "the alternative. Prefer the dearer one only for something the person said, passing "
            "their words as person_preference"
        )


def _figures(option: Option) -> str:
    """The option's term and figures as they stand now, amounts to the shekel, so a reply about
    a recommendation never quotes figures from before a term change."""
    (term,) = set(_terms(option))
    return _inline({"term_months": term, **_money_figures(option)})


_AGAINST_MARKET: dict[RateAgainstMarket, str] = {
    "above": "above",
    "similar": "similar to",
    "below": "below",
}


def track_text(option: Option) -> str:
    """The option's single track in the words the model reads: its rate and its linkage."""
    (track,) = cast(list[Mapping[str, object]], option.loan["tracks"])
    if track["rate_kind"] == "prime":
        rate = f"prime + {track['prime_spread']}"
    else:
        rate = f"fixed {track['annual_rate']}"
    return f"{rate}, {'linked' if track['cpi_linked'] else 'not linked'}"


def price_text(option: Option) -> str:
    """What the option costs over its principal at today's terms and, when the engine priced its
    rate, the rate today against the market, so the model states the price without computing
    it. A linked rate is on top of the CPI, so it is not set against the unlinked average."""
    tracks = cast(list[Mapping[str, object]], option.loan["tracks"])
    linked = any(track["cpi_linked"] for track in tracks)
    cost = f"interest_cost {shekels(option.interest_cost)} on {shekels(option.principal)}"
    if linked:
        cost += ", the CPI's rise included"
    price = option.summary.price
    if price is None:
        return cost
    if price.against_market is None:
        rate = (
            f"rate_today {price.rate_today}% on top of the CPI, not comparable with the unlinked "
            "average"
        )
    else:
        rate = (
            f"rate_today {price.rate_today}%, {_AGAINST_MARKET[price.against_market]} the "
            f"average bank rate on consumer loans of {price.market_rate}% as of "
            f"{price.market_rate_month:%Y-%m}"
        )
    return f"{cost}; {rate}"


def _inline(values: Mapping[str, object]) -> str:
    """Several values on one line of a summary, as "key value" pairs."""
    return ", ".join(f"{key} {_summary_value(value)}" for key, value in values.items())


def _shorter_term_step(shorter: _ShorterTerm) -> str:
    """The instruction a recommendation's result gives the model for a shorter term that fits."""
    return (
        f"the preferred option also fits the ceiling at {shorter.term_months} months, with a "
        f"worst-case monthly payment of {shorter.worst_payment} and "
        f"{shorter.saving} less in total than at {shorter.from_term_months} months. End the "
        f"turn with ask_term with term_months {shorter.term_months}: its card states these "
        "figures, so the person confirms the shorter term there or keeps theirs, and the "
        "reply says nothing of them. Once they confirm, it is simply the check's term: never "
        "call it shorter or cheaper, or say the option 'also' fits at it. If they keep their "
        "term, do not offer it again"
    )


def _margin(option: Option, ceiling: Decimal) -> str:
    """How far the option's worst-case recurring payment is below the ceiling, in shekels and as
    a share of the ceiling."""
    margin = ceiling - option.summary.risk_payment
    share = (margin / ceiling * 100).quantize(Decimal(1), ROUND_HALF_UP)
    return f"{margin.quantize(Decimal(1), ROUND_HALF_UP)} ({share}%)"


def english_words(text: str, people_said: Iterable[str]) -> list[str]:
    """The English words of text the person reads, other than words the person wrote themselves,
    such as a lender's name, sorted and each once."""
    theirs = {word for said in people_said for word in ENGLISH_WORD.findall(said)}
    return sorted(set(ENGLISH_WORD.findall(text)) - theirs)


def _require_hebrew(argument: str, text: object) -> None:
    """Refuses text the person sees when it has an English word; None is an omitted argument."""
    if text is None:
        return
    assert isinstance(text, str)
    word = ENGLISH_WORD.search(text)
    if word is not None:
        raise ToolError(
            f"{argument} has the English word {word.group()!r}, and the person reads Hebrew only; "
            "write it entirely in Hebrew, never naming a tool or a field, and spell a name in "
            "Hebrew letters"
        )


def _principal(loan: Mapping[str, object]) -> Decimal:
    """The loan's total principal; raises ToolError when a track's principal is neither a string
    nor an integer, since a binary float cannot carry money exactly."""
    tracks = loan["tracks"]
    assert isinstance(tracks, list)
    total = Decimal(0)
    for index, track in enumerate(tracks):
        assert isinstance(track, Mapping)
        value = track["principal"]
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ToolError(
                f'loan.tracks[{index}].principal must be a decimal string such as "80000", '
                f"not {value!r}"
            )
        total += Decimal(value)
    return total


def _ceiling(amount: object) -> Decimal:
    ceiling = _amount("payment_ceiling", amount)
    if ceiling <= 0:
        raise ToolError(
            "payment_ceiling must be greater than zero; a person who can pay nothing a month "
            "cannot take a loan, so tell them so"
        )
    return ceiling


def _amount(name: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise ToolError(f'{name} must be a decimal string such as "55000", not {value!r}')
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ToolError(f"{name} is not a number: {value!r}") from None
    if not amount.is_finite():
        raise ToolError(f"{name} must be a finite number, not {value!r}")
    return amount


def _offer_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(
            f"offer_date must be an ISO date such as 2026-10-20, not {value!r}"
        ) from None


# Below these shares of the larger figure a difference is not worth a reason: a monthly payment
# a few shekels apart is not mentioned, and a total a little apart is "slightly" cheaper.
NEGLIGIBLE_PAYMENT_SHARE = Decimal("0.02")
SLIGHT_TOTAL_SHARE = Decimal("0.03")


def _same_option(existing: Option, option: Option) -> bool:
    """Two lenders may quote the same terms, so the lender tells options apart, except that a
    name one letter away from the saved one is the same lender misspelled."""

    def terms(of: Option) -> tuple[object, ...]:
        return (of.source, of.offer_date, of.max_term_months, of.summary)

    return terms(existing) == terms(option) and _same_lender(existing.lender, option.lender)


def _same_lender(saved: str | None, given: str | None) -> bool:
    if saved is None or given is None:
        return saved == given
    return _one_edit_apart(saved.strip(), given.strip())


def _one_edit_apart(a: str, b: str) -> bool:
    """Whether the two names are equal or differ by one letter added, removed or replaced."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    for index, (left, right) in enumerate(zip(a, b, strict=False)):
        if left != right:
            skip = 0 if len(a) == len(b) else 1
            return a[index + 1 - skip :] == b[index + 1 :]
    return True


def _terms(option: Option) -> list[object]:
    return [
        track["term_months"] for track in cast(list[Mapping[str, object]], option.loan["tracks"])
    ]


def _comparison(option: Option, other: Option) -> str:
    """How this option's first payment and total differ from another option's, each classed by
    how it should weigh in the person's reading: a negligible payment gap is not mentioned; a
    slight total gap is said with "במקצת", since the total still decides; a clear gap plainly."""
    mine, theirs = option.summary, other.summary
    payment = _gap(mine.first_payment, theirs.first_payment, NEGLIGIBLE_PAYMENT_SHARE, "זניח")
    total = _gap(mine.total_paid, theirs.total_paid, SLIGHT_TOTAL_SHARE, "במקצת")
    return f"against option {other.id}: first_payment {payment}, total_paid {total}"


def _gap(mine: Decimal, theirs: Decimal, share: Decimal, small: str) -> str:
    """The gap with its direction and class: small below the share of the larger figure. The
    words are Hebrew, since the model quotes them in the person's reply."""
    gap = mine - theirs
    if gap == 0:
        return f"שווה ({small})"
    direction = "נמוך" if gap < 0 else "גבוה"
    weight = small if abs(gap) < share * max(mine, theirs) else "ברור"
    return f"{abs(gap).quantize(Decimal(1))} {direction} ({weight})"


def _option_data(option: Option) -> dict[str, object]:
    return {
        "option_id": option.id,
        "loan": option.loan,
        "source": option.source,
        "lender": option.lender,
        "offer_date": _json_value(option.offer_date),
        "max_term_months": option.max_term_months,
        "figures": option.summary.to_json(),
    }


# The figures of the worst period history holds for a loan whose payment moves.
_WORST_CASE_FIGURES = ("worst_peak_payment", "worst_start", "worst_end")


def _money_figures(option: Option) -> dict[str, object]:
    """The option's figures but its price, with every amount rounded to the shekel, as the person
    reads them; those figures' amounts are all money, while the price holds rates. A payment
    that never changes has no worst period in history: in place of its three empty figures the
    result says so, so the model has no period to write about."""
    figures = asdict(option.summary)
    del figures["price"]
    steady = option.summary.worst_peak_payment is None
    told: dict[str, object] = {}
    for key, value in figures.items():
        if steady and key in _WORST_CASE_FIGURES:
            told["payment_changes"] = "never"
        else:
            told[key] = shekels(value) if isinstance(value, Decimal) else value
    return told


def shekels(amount: Decimal) -> Decimal:
    """The amount to the shekel, as the person reads it."""
    return amount.quantize(Decimal(1), ROUND_HALF_UP)


def _json_ready(values: Mapping[str, object]) -> dict[str, object]:
    return {key: _json_value(value) for key, value in values.items()}


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return value


def finances_figures(finances: Finances) -> dict[str, object]:
    """Each figure of the finances, or "not told", and the figures still missing."""
    missing = finances.missing()
    return {
        **{
            name: "not told" if value is None else value for name, value in asdict(finances).items()
        },
        "missing": ", ".join(missing) if missing else "none",
    }


def summary(values: Mapping[str, object]) -> str:
    return "\n".join(f"{key}: {_summary_value(value)}" for key, value in values.items())


def _summary_value(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(_json_value(value))
