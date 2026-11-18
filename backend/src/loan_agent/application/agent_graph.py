"""The agent loop: a language model leads the Hebrew conversation and calls the engine's tools and
the check tools until it has a reply for the person, has asked them a question through ask,
ask_term, ask_offer or compare_terms, or read_offer has put an offer's readings on their screen;
each check's conversation is one checkpoint thread.

- build_agent_graph: the model node and the tool node over the thread's messages, as an
  AgentGraph; a reply's tool calls skip the tool node and are refused when an argument holds a
  NUL character, and a prompt the provider's usage filter flags is sent once more
- check_config: the run configuration naming the person and the check, with the turn's step
  limit
- delete_conversation, copy_conversation: remove a check's saved conversation, or start
  another check's with its messages
- last_message: the last message of a check's conversation
- people_said: the texts of the person's own messages, whose English words a reply may repeat
- SYSTEM_PROMPT: the Hebrew instructions sent ahead of the messages on every model call, followed
  by the turn_state block of the check's stored loan, ceiling, finances, options and awaiting
  offers
- The check tools' argument schemas, with money as decimal strings like the engine's own schema

The person and the check come from the run configuration, never from the model's arguments, so
the model can only act on the check it is talking about.
"""

import json
import logging
import re
from collections.abc import Sequence
from importlib.resources import files
from typing import Annotated, Any, Literal, Self

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import InjectedState, ToolNode
from pydantic import BaseModel, ConfigDict, Field, model_validator

from loan_agent.application.check_tools import (
    READING_ON_SCREEN,
    TERM_STEP,
    ChartSeries,
    CheckTools,
    TermDirection,
    ToolDeps,
    ToolError,
    english_words,
)
from loan_agent.application.turn_state import turn_state
from loan_agent.domain.models import ReadingKind, TypeWord

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (files(__package__) / "prompts" / "system_he.md").read_text(encoding="utf-8")

# The graph steps one turn may take before it fails; a model call is one step, and the tool calls
# it asks for, run together, are one more. A first recommendation takes about 13 steps, so the
# limit stops a model that keeps calling tools after about 20 model calls; the per-person message
# cap (Settings.agent_turn_limit) bounds messages, not the model calls inside one.
TURN_STEP_LIMIT = 40

# How many model replies in a row may ask for the same tool calls with the same arguments. The
# results of a repeated call cannot differ, so a model that repeats it is stuck, and the turn fails
# there rather than paying for the same call up to TURN_STEP_LIMIT.
SAME_CALLS_LIMIT = 2


class RepeatedToolCallsError(Exception):
    """The model asked for the same tool calls more than SAME_CALLS_LIMIT times in a row."""


RECOMMENDATION_HEADING = "ההמלצה שלי"
"""The section of a reply that recommends, as the system prompt writes it. The person's card
changes only through present_recommendation, so this section without that call is a false
promise."""
EVALUATION_HEADING = "ההצעה שבדקתי"
"""The section of a reply that evaluates the check's only option in place of recommending one;
the card changes through present_recommendation all the same."""
_RECOMMENDATION_SECTION = re.compile(
    rf"^\W*(?:{RECOMMENDATION_HEADING}|{EVALUATION_HEADING})\W*$", re.MULTILINE
)
_REDO_THE_RECOMMENDATION = (
    "Your reply was discarded and the person did not see it: it has a recommendation section, but "
    "present_recommendation did not succeed in this turn, so nothing was calculated or saved. Make "
    "the calls the recommendation needs, ending with present_recommendation, and write the reply "
    "from their results. If no recommendation is possible, write the reply without that section."
)

_REWRITE_IN_HEBREW = (
    "Your reply was discarded and the person did not see it: it has English words, and the "
    "person reads Hebrew only. Write the same reply again entirely in Hebrew, with the exact "
    "wording the instructions give; keep only a name the person wrote in English as they wrote it."
)

_REWRITE_WITHOUT_NUL = (
    "Your reply was discarded and the person did not see it: its text holds a NUL character "
    "(\\u0000), which cannot be stored. Write the same reply again without that character."
)

_USER_ID = "user_id"
# The checkpoint thread of a check is named by the check's id.
_CHECK_ID = "thread_id"

_DECIMAL = r"^\d+(\.\d+)?$"
_SIGNED_DECIMAL = r"^-?\d+(\.\d+)?$"


def _money(description: str) -> Any:
    return Field(pattern=_DECIMAL, description=f"{description}, as a decimal string like '1550'")


def _optional_money(description: str) -> Any:
    return Field(
        default=None,
        pattern=_DECIMAL,
        description=f"{description}, as a decimal string like '1550'; omit when not told",
    )


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetLoanArgs(_Args):
    purpose: str | None = Field(
        default=None,
        description="What the loan is for, in one or two Hebrew words: one of the page's purpose "
        "choices when it fits, else the person's own words; omit when the person named none",
    )
    amount: str = _money(
        "The loan the person needs, ₪: the amount they stated, or the price less their own capital"
    )
    payment_ceiling: str | None = _optional_money(
        "The highest monthly payment the person said suits them, ₪, when the message that states "
        'the loan names one ("עד 1,000 בחודש", "אוכל להחזיר עד 1,000"); omit when it names none'
    )


class OfferTrackArgs(_Args):
    rate_kind: Literal["fixed", "prime"] = Field(description="'fixed' or 'prime'")
    rate: str | None = Field(
        default=None,
        pattern=_SIGNED_DECIMAL,
        description="Annual percent of a fixed track ('3.5'), or the margin over prime of a prime "
        "track ('0.5', '-0.25' under prime), as a decimal string; omit when the person did not "
        "say it",
    )
    cpi_linked: bool = Field(
        default=False,
        description="true when the person said a fixed track is linked to the index; a prime "
        "track is never linked",
    )


class AskOfferArgs(_Args):
    lender: str | None = Field(default=None, description="Who made the offer, when said")
    tracks: list[OfferTrackArgs] = Field(
        default_factory=list, description="The tracks the person mentioned, when any"
    )
    max_term_months: int | None = Field(
        default=None, description="The longest term the offer allows, months, when said"
    )
    # Filled by the tool node from the graph state and hidden from the model's schema.
    state: Annotated[MessagesState, InjectedState]


class AskTermArgs(_Args):
    term_months: int | None = Field(
        default=None,
        description="The number of months the person typed, for a card with that term's first "
        "payment; omit for the card's proposed term",
    )
    # Filled by the tool node from the graph state and hidden from the model's schema.
    state: Annotated[MessagesState, InjectedState]


class CompareTermsArgs(_Args):
    direction: TermDirection = Field(
        description="shorter when the person asks for fewer payments or a shorter term, longer "
        "when they ask for more payments, a longer term or a lower monthly payment"
    )
    # Filled by the tool node from the graph state and hidden from the model's schema.
    state: Annotated[MessagesState, InjectedState]


class SetTermArgs(_Args):
    term_months: int = Field(description="The term the person confirmed on the term card, months")


class SetCeilingArgs(_Args):
    payment_ceiling: str = _money("The highest monthly payment the person said suits them, ₪")


class UpdateFinancesArgs(_Args):
    net_fixed_income: str | None = _optional_money(
        "Fixed income after tax, from the payslip, with the variable income that arrives even in "
        "a weak month, ₪ per month"
    )
    fixed_expenses: str | None = _optional_money(
        "Rent, bills, shopping, leisure and the payments on existing loans, ₪ per month"
    )


class TrackArgs(_Args):
    principal: str = _money("Amount borrowed on this track, ₪")
    term_months: int = Field(description="Term, months")
    rate_kind: Literal["fixed", "prime"] = Field(
        description="'fixed' with annual_rate, or 'prime' with prime_spread"
    )
    annual_rate: str | None = Field(
        default=None,
        pattern=_DECIMAL,
        description="Annual percent ('7.9' means 7.9%), as a decimal string; fixed tracks only",
    )
    prime_spread: str | None = Field(
        default=None,
        pattern=_SIGNED_DECIMAL,
        description="Annual percent over prime ('1.5' means prime + 1.5%; '-0.25' means prime "
        "minus 0.25%), as a decimal string; prime tracks only",
    )
    cpi_linked: bool = Field(description="true when the balance is linked to the consumer index")
    method: Literal["spitzer", "equal_principal", "balloon"] = Field(
        description="'spitzer' (equal payments), 'equal_principal', or 'balloon' with "
        "balloon_amount"
    )
    balloon_amount: str | None = _optional_money("Repaid in one sum in the last month, ₪")
    one_time_fee: str | None = _optional_money("Fee paid once when the loan is taken, ₪")
    monthly_fee: str | None = _optional_money("Fee added to every payment, ₪ per month")


class SaveExamplesArgs(_Args):
    """save_examples takes no argument: the check holds the loan amount and the term."""


class SaveOfferArgs(_Args):
    tracks: list[TrackArgs] = Field(
        min_length=1,
        description="Every track the offer names, each for the whole loan amount: a lender's "
        "tracks are alternatives, and each is saved as an option of its own",
    )
    lender: str | None = Field(default=None, description="Who made the offer")
    offer_date: str | None = Field(
        default=None, description="Date of the offer, ISO like 2026-10-20"
    )
    max_term_months: int | None = Field(
        default=None,
        description="The longest term of an offer that leaves the term open ('up to 84 months'), "
        "with each track's term_months the term to save, which a refusal names; omit when the "
        "offer fixes the term or the person chose it",
    )


class ReadOfferArgs(_Args):
    lender: str | None = Field(default=None, description="Who made the offer, when said")
    amount: str | None = _optional_money("The amount the lender quoted")
    term_months: int | None = Field(
        default=None, description="The months the lender quoted, when said"
    )
    stated_rate: str | None = Field(
        default=None,
        pattern=_SIGNED_DECIMAL,
        description="The number stated with the offer, as the person wrote it ('6', '6.45'), as "
        "a decimal string; omit when the offer states none",
    )
    monthly_payment: str | None = _optional_money("The monthly payment the lender quoted")
    type_words: list[TypeWord] = Field(
        default=[],
        description="The type words the person used: 'prime' for פריים, 'fixed' for קבוע, "
        "'linked' for צמוד",
    )
    awaiting_id: str | None = Field(
        default=None,
        description="The id from awaiting_offers when the message adds to or corrects that "
        "offer; omit for a new offer",
    )


class AnswerOfferAmountArgs(_Args):
    awaiting_id: str = Field(
        description="The id from awaiting_offers of the offer quoted for less than the loan"
    )
    covers: bool = Field(
        description="True when the lender lends the check's loan amount on the same terms"
    )
    reading: ReadingKind | None = Field(
        default=None,
        description="With covers, the reading from the offer's readings that the lender meant; "
        "omit when the offer holds one reading",
    )


class PresentRecommendationArgs(_Args):
    preferred_option_id: str = Field(description="option_id from save_examples or save_offer")
    reasoning: str = Field(description="Why this option fits the person, in Hebrew")
    alternative_option_id: str | None = Field(
        default=None, description="option_id of a second choice, if any"
    )
    person_preference: str | None = Field(
        default=None,
        description="What the person said that makes the preferred option suit them although "
        "another of its kind costs less in total, in their words; omit it otherwise",
    )


QuestionField = Literal[
    "purpose", "amount", "own_capital", "net_fixed_income", "fixed_expenses", "payment_ceiling"
]


class AskQuestion(_Args):
    field: QuestionField | None = Field(
        default=None,
        description="The loan, finances or ceiling field asked for; the page shows its own "
        "control. Omit when asking a free question with text",
    )
    offer_clone: bool = Field(
        default=False,
        description="True to ask whether to clone the check before changing its "
        "recommendation; the page shows its own question and choices, so give no field, text "
        "or choices",
    )
    text: str | None = Field(
        default=None,
        min_length=1,
        description="A free question in Hebrew; omit when asking for a field",
    )
    choices: list[str] | None = Field(
        default=None,
        min_length=2,
        description="The answers the person taps, in Hebrew; free questions only. Always given "
        "for a question answered by yes or no or by one of a few answers; omitted only "
        "when the person answers in their own words or with a number",
    )

    @model_validator(mode="after")
    def _one_of_field_and_text(self) -> Self:
        if self.offer_clone:
            if (self.field, self.text, self.choices) != (None, None, None):
                raise ValueError("a clone offer takes no field, text or choices")
            return self
        if (self.field is None) == (self.text is None):
            raise ValueError("give exactly one of field and text")
        if self.choices is not None and self.text is None:
            raise ValueError("choices go with a free question in text, not with a field")
        return self


class ShowChartArgs(_Args):
    series: ChartSeries = Field(
        description="'prime' for the prime rate by month, 'cpi' for the consumer price index's "
        "monthly change"
    )
    months: int = Field(description="How many latest months to draw, at most 120")


class AskArgs(_Args):
    question: AskQuestion
    lead_in: str | None = Field(
        default=None,
        description=(
            "Usually left out: the page shows the field's own label and hint. Only a short "
            "Hebrew condition the label does not state, never why the figure is needed; or, "
            "when the calculation cannot go on, the reason with its amounts"
        ),
    )
    # Filled by the tool node from the graph state and hidden from the model's schema.
    state: Annotated[MessagesState, InjectedState]


AgentGraph = CompiledStateGraph[MessagesState, None, MessagesState, MessagesState]


def check_config(user_id: str, check_id: str) -> RunnableConfig:
    return {
        "configurable": {_USER_ID: user_id, _CHECK_ID: check_id},
        "recursion_limit": TURN_STEP_LIMIT,
    }


async def delete_conversation(graph: AgentGraph, check_id: str) -> None:
    assert isinstance(graph.checkpointer, BaseCheckpointSaver)
    await graph.checkpointer.adelete_thread(check_id)


async def copy_conversation(graph: AgentGraph, source_id: str, target_id: str) -> None:
    """Starts the target's thread with one checkpoint holding the source's messages; the next
    turn on the target runs from them as if they had been said there."""
    source = await graph.aget_state({"configurable": {_CHECK_ID: source_id}})
    if source.values:
        target: RunnableConfig = {"configurable": {_CHECK_ID: target_id}}
        await graph.aupdate_state(target, source.values, as_node="model")


async def record_exchange(
    graph: AgentGraph, config: RunnableConfig, messages: list[BaseMessage]
) -> None:
    """Appends messages answered outside the model to the check's conversation, as if a turn had
    said them, so the model's next turn reads them."""
    await graph.aupdate_state(config, {"messages": messages}, as_node="model")


async def last_message(graph: AgentGraph, check_id: str) -> BaseMessage | None:
    """The last message of the check's conversation; None before its first turn."""
    state = await graph.aget_state({"configurable": {_CHECK_ID: check_id}})
    return state.values["messages"][-1] if state.values else None


def _tools_for(config: RunnableConfig, deps: ToolDeps) -> CheckTools:
    configurable = config["configurable"]
    return CheckTools(configurable[_USER_ID], configurable[_CHECK_ID], deps)


def _check_model_tools(deps: ToolDeps) -> list[BaseTool]:
    async def set_loan(
        amount: str,
        config: RunnableConfig,
        purpose: str | None = None,
        payment_ceiling: str | None = None,
    ) -> str:
        return await _tools_for(config, deps).set_loan(purpose, amount, payment_ceiling)

    async def ask_term(
        config: RunnableConfig,
        state: Annotated[MessagesState, InjectedState],
        term_months: int | None = None,
    ) -> str:
        _require_one_question(state)
        return await _tools_for(config, deps).ask_term(term_months)

    async def compare_terms(
        direction: TermDirection,
        config: RunnableConfig,
        state: Annotated[MessagesState, InjectedState],
    ) -> str:
        _require_one_question(state)
        return await _tools_for(config, deps).compare_terms(direction)

    async def ask_offer(
        config: RunnableConfig,
        state: Annotated[MessagesState, InjectedState],
        lender: str | None = None,
        tracks: list[OfferTrackArgs] | None = None,
        max_term_months: int | None = None,
    ) -> str:
        _require_one_question(state)
        said = [] if tracks is None else [track.model_dump() for track in tracks]
        return await _tools_for(config, deps).ask_offer(lender, said, max_term_months)

    async def set_term(term_months: int, config: RunnableConfig) -> str:
        return await _tools_for(config, deps).set_term(term_months)

    async def set_ceiling(payment_ceiling: str, config: RunnableConfig) -> str:
        return await _tools_for(config, deps).set_ceiling(payment_ceiling)

    async def update_finances(config: RunnableConfig, **fields: object) -> str:
        told = {name: value for name, value in fields.items() if value is not None}
        return await _tools_for(config, deps).update_finances(**told)

    async def save_examples(config: RunnableConfig) -> str:
        return await _tools_for(config, deps).save_examples()

    async def save_offer(
        tracks: list[TrackArgs],
        config: RunnableConfig,
        lender: str | None = None,
        offer_date: str | None = None,
        max_term_months: int | None = None,
    ) -> str:
        offered = [track.model_dump(exclude_none=True) for track in tracks]
        return await _tools_for(config, deps).save_offer(
            offered, lender, offer_date, max_term_months
        )

    async def read_offer(
        config: RunnableConfig,
        lender: str | None = None,
        amount: str | None = None,
        term_months: int | None = None,
        stated_rate: str | None = None,
        monthly_payment: str | None = None,
        type_words: Sequence[TypeWord] = (),
        awaiting_id: str | None = None,
    ) -> str:
        return await _tools_for(config, deps).read_offer(
            lender, amount, term_months, stated_rate, monthly_payment, type_words, awaiting_id
        )

    async def answer_offer_amount(
        awaiting_id: str,
        covers: bool,
        config: RunnableConfig,
        reading: ReadingKind | None = None,
    ) -> str:
        return await _tools_for(config, deps).answer_offer_amount(awaiting_id, covers, reading)

    async def present_recommendation(
        preferred_option_id: str,
        reasoning: str,
        config: RunnableConfig,
        alternative_option_id: str | None = None,
        person_preference: str | None = None,
    ) -> str:
        return await _tools_for(config, deps).present_recommendation(
            preferred_option_id, reasoning, alternative_option_id, person_preference
        )

    async def show_chart(series: str, months: int, config: RunnableConfig) -> str:
        return await _tools_for(config, deps).show_chart(series, months)

    async def ask(
        question: AskQuestion,
        config: RunnableConfig,
        state: Annotated[MessagesState, InjectedState],
        lead_in: str | None = None,
    ) -> str:
        _require_one_question(state)
        return await _tools_for(config, deps).ask(question.model_dump(), lead_in)

    return [
        StructuredTool.from_function(
            coroutine=set_loan,
            name="set_loan",
            description="Save the loan the person needs: its amount and, when they named them, its "
            "purpose and their monthly payment ceiling. The amount is the one simulated and "
            "recommended; nothing sizes it. Refused with the engine's limit when the amount is "
            "outside what the simulator prices.",
            args_schema=SetLoanArgs,
        ),
        StructuredTool.from_function(
            coroutine=ask_term,
            name="ask_term",
            description="Show the term card: a first calculation of a term with its first "
            "payment, and a form with the term and the payment ceiling under one confirm button, "
            "and the turn ends; the answer arrives as the person's next message. Without "
            "term_months the card proposes the term from the check's ceiling or, with none, from "
            "an assumed first payment, and states which.",
            args_schema=AskTermArgs,
        ),
        StructuredTool.from_function(
            coroutine=compare_terms,
            name="compare_terms",
            description="Show the terms card: the recommended option priced at its term and at "
            f"the next terms {TERM_STEP} months apart in the direction the person asked, each with "
            "its payment today and in the worst historical period against the ceiling, with a "
            "button to choose each; the turn ends, and a chosen term arrives as the person's next "
            "message. Call it when the person asks for a shorter or longer term without naming a "
            "number. Refused, with what to tell the person, when no term in that direction is "
            "possible.",
            args_schema=CompareTermsArgs,
        ),
        StructuredTool.from_function(
            coroutine=ask_offer,
            name="ask_offer",
            description="Call this when the person says they received a real offer and the "
            "message holds no monthly payment and lacks the lender, a track's interest or the "
            "number of months; an offer that states a monthly payment goes to read_offer, which "
            "derives the interest from it. "
            "Opens a form on the person's screen with what they said filled in, and the turn "
            "ends; the answer arrives as the person's next message. Do not call it for an offer "
            "that mentions a balloon, a fee, a fixed number of months or an amount cap.",
            args_schema=AskOfferArgs,
        ),
        StructuredTool.from_function(
            coroutine=set_term,
            name="set_term",
            description="Save the term the person confirmed on the term card.",
            args_schema=SetTermArgs,
        ),
        StructuredTool.from_function(
            coroutine=set_ceiling,
            name="set_ceiling",
            description="Save the monthly payment the person said is the most that suits them as "
            "the check's payment ceiling, replacing any ceiling the check held.",
            args_schema=SetCeilingArgs,
        ),
        StructuredTool.from_function(
            coroutine=update_finances,
            name="update_finances",
            description="Save the person's net fixed income or fixed expenses on this check. Send "
            "only the figures they told or corrected; every amount is net, in ₪. Once both are "
            "known the check's payment ceiling is derived from them. Returns the figures, what "
            "is still missing and the ceiling.",
            args_schema=UpdateFinancesArgs,
        ),
        StructuredTool.from_function(
            coroutine=save_examples,
            name="save_examples",
            description="Save the three example tracks for the check's loan amount and "
            "confirmed term in one call: a fixed and a prime track, both unlinked, at the Bank "
            "of Israel's published average rate, and a fixed track linked to the CPI on the "
            "terms a pension fund publishes. The engine prices each and all three are kept as "
            "options of this check, or none; an example already saved is kept. Returns each "
            "example's track, option_id and figures. A real offer is saved with save_offer. "
            "Refused before the term is confirmed, and once the check holds a real offer of its "
            "loan amount.",
            args_schema=SaveExamplesArgs,
        ),
        StructuredTool.from_function(
            coroutine=save_offer,
            name="save_offer",
            description="Save a real offer the person received, with every track it names in "
            "one call: each track is priced for the check's loan amount and kept as an option "
            "of its own, and when one is refused none is saved. Returns each track's option_id "
            "and figures. With max_term_months a track is refused at any term but the one the "
            "engine's search over that track gives. Saving an offer removes the check's "
            "examples, and a recommendation that names one.",
            args_schema=SaveOfferArgs,
        ),
        StructuredTool.from_function(
            coroutine=read_offer,
            name="read_offer",
            description="Call this for an offer the person describes in words when the "
            "description holds a monthly payment, or leaves the loan's type open: a bare number "
            "that may be a margin over prime or the whole rate, or no rate at all. Pass only what "
            "the person said: the lender, the amount and months the lender quoted, the number "
            "stated with the offer, the monthly payment, and the type words used. The screen "
            "shows the result. To add a detail to an offer that awaits its lender, pass its "
            "awaiting_id from the state message with the new detail alone.",
            args_schema=ReadOfferArgs,
        ),
        StructuredTool.from_function(
            coroutine=answer_offer_amount,
            name="answer_offer_amount",
            description="Call this when the person tells the lender's answer about an awaiting "
            "offer quoted for less than the check's loan: whether the lender lends the loan "
            "amount on the same terms. With covers the offer is saved at the loan amount; "
            "without it the offer leaves the check and the screen says it does not enter the "
            "comparison.",
            args_schema=AnswerOfferAmountArgs,
        ),
        StructuredTool.from_function(
            coroutine=present_recommendation,
            name="present_recommendation",
            description="Present the recommendation card: the preferred option and an optional "
            "alternative, with your reasoning. Without a ceiling the card says it is not yet "
            "checked against what the person can pay. Refused, with the reason and the remedy "
            "to offer, when a named option's worst-case payment is above the ceiling, and when "
            "another option of the preferred one's term fits and costs less in total.",
            args_schema=PresentRecommendationArgs,
        ),
        StructuredTool.from_function(
            coroutine=ask,
            name="ask",
            description="Ask the person one question. The page shows it with the right control "
            "and a skip, and the turn ends; the answer arrives as their next message. A field "
            "the check already holds is refused.",
            args_schema=AskArgs,
        ),
        StructuredTool.from_function(
            coroutine=show_chart,
            name="show_chart",
            description="Draw a chart of the prime or of the CPI's monthly change for the latest "
            "months in the conversation, from the market data the loans are priced with. Use it "
            "when the person asks to see how the prime or prices moved.",
            args_schema=ShowChartArgs,
        ),
    ]


# The tools that put a question on the person's screen and end the turn.
_QUESTION_TOOLS = frozenset({"ask", "ask_term", "ask_offer", "compare_terms"})


def _require_one_question(state: MessagesState) -> None:
    if _question_call_count(state) > 1:
        raise ToolException(
            "one question per turn: call ask, ask_term, ask_offer or compare_terms once, with the "
            "one question to ask now"
        )


def _last_ai_message(state: MessagesState) -> AIMessage:
    return next(m for m in reversed(state["messages"]) if isinstance(m, AIMessage))


def _question_call_ids(state: MessagesState) -> set[str | None]:
    calls = _last_ai_message(state).tool_calls
    return {call["id"] for call in calls if call["name"] in _QUESTION_TOOLS}


def _question_call_count(state: MessagesState) -> int:
    return sum(call["name"] in _QUESTION_TOOLS for call in _last_ai_message(state).tool_calls)


def _recommends_without_the_tool(reply: AIMessage, messages: Sequence[BaseMessage]) -> bool:
    """A model can write the recommendation as text and skip the tools. The check runs before the
    reply reaches the conversation, so a discarded reply is never stored; a second one stands
    whatever it says, because a reply about a case with no recommendation may share the heading."""
    if reply.tool_calls or _RECOMMENDATION_SECTION.search(reply.text) is None:
        return False
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return True
        if (
            isinstance(message, ToolMessage)
            and message.name == "present_recommendation"
            and message.status != "error"
        ):
            return False
    raise AssertionError("a turn starts with the person's message")


def _calls_of(reply: AIMessage) -> list[tuple[str, str]]:
    return sorted(
        (call["name"], json.dumps(call["args"], sort_keys=True)) for call in reply.tool_calls
    )


def _require_new_calls(reply: AIMessage, messages: Sequence[BaseMessage]) -> None:
    """Raises RepeatedToolCallsError when the reply asks for the tool calls the turn's last
    SAME_CALLS_LIMIT replies already asked for."""
    if not reply.tool_calls:
        return
    earlier: list[AIMessage] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage) or len(earlier) == SAME_CALLS_LIMIT:
            break
        if isinstance(message, AIMessage):
            earlier.append(message)
    if len(earlier) == SAME_CALLS_LIMIT and all(
        _calls_of(reply) == _calls_of(message) for message in earlier
    ):
        names = ", ".join(sorted({call["name"] for call in reply.tool_calls}))
        raise RepeatedToolCallsError(f"the model repeated the same calls: {names}")


def people_said(messages: Sequence[BaseMessage]) -> list[str]:
    """The texts of the person's own messages in a conversation."""
    return [message.text for message in messages if isinstance(message, HumanMessage)]


def _correction_for(reply: AIMessage, messages: Sequence[BaseMessage], check_id: str) -> str | None:
    """What the model must redo before its reply reaches the conversation: a recommendation
    written without its tool, a NUL character in its text, which Postgres cannot store in the
    reply's event, or English words the person did not write themselves, which are
    logged as a warning so their source can be found. A reply is redone once, whatever the
    second one says, so a turn never loops on a correction."""
    if _recommends_without_the_tool(reply, messages):
        return _REDO_THE_RECOMMENDATION
    if "\x00" in reply.text:
        return _REWRITE_WITHOUT_NUL
    english = english_words(reply.text, people_said(messages))
    if english:
        log.warning("reply rejected for English words %s in check %s", ", ".join(english), check_id)
        return _REWRITE_IN_HEBREW
    return None


def _after_tools(state: MessagesState) -> Literal["model", "__end__"]:
    """Ends the turn once ask, ask_term, ask_offer or compare_terms put a question on the person's
    screen, or when every result of the reply's calls is a reading on the screen, which the person
    answers there. A refused question, an identified offer, a refusal and any other tool's result
    go back to the model."""
    asked = _question_call_ids(state)
    results: list[ToolMessage] = []
    for message in reversed(state["messages"]):
        if isinstance(message, AIMessage):
            break
        if isinstance(message, ToolMessage):
            results.append(message)
    if any(result.tool_call_id in asked and result.status != "error" for result in results):
        return "__end__"
    if results and all(
        result.status != "error" and result.content == READING_ON_SCREEN for result in results
    ):
        return "__end__"
    return "model"


def _tool_error_text(error: ToolError | ToolException) -> str:
    """The refusal or the engine's error, returned to the model as the tool's result so it can
    correct the call; ToolNode lets every other exception end the turn."""
    return str(error)


_NUL_REFUSED = (
    "no call of this reply ran: its arguments hold a NUL character (\\u0000), which cannot be "
    "stored; send the calls again with the same arguments and without that character"
)


def _holds_nul(value: Any) -> bool:
    """Whether a tool call's argument, or any text nested in it, holds a NUL character."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_holds_nul(item) for item in value.values())
    if isinstance(value, list):
        return any(_holds_nul(item) for item in value)
    return False


def _after_model(state: MessagesState) -> Literal["tools", "refuse_nul", "__end__"]:
    """Sends a reply's tool calls to the tools, unless an argument holds a NUL character.
    Postgres stores no NUL in text or JSON, so a tool that saved such an argument would end the
    turn after other calls of the same reply had written their records."""
    reply = _last_ai_message(state)
    if not reply.tool_calls:
        return "__end__"
    if any(_holds_nul(call["args"]) for call in reply.tool_calls):
        return "refuse_nul"
    return "tools"


def _refuse_nul(state: MessagesState) -> MessagesState:
    """Answers every tool call of the last reply with _NUL_REFUSED, so the model sends them
    again."""
    return {
        "messages": [
            ToolMessage(_NUL_REFUSED, name=call["name"], tool_call_id=call["id"], status="error")
            for call in _last_ai_message(state).tool_calls
        ]
    }


# The words by which OpenAI refuses a prompt its usage filter flags; the error is a plain
# APIError, told apart from the provider's other failures only by its message. The filter
# misfires on ordinary loan conversations, and the same prompt usually passes when sent again.
_PROMPT_FLAGGED = "flagged as potentially violating"


async def _reply_of(
    bound: Any, conversation: Sequence[BaseMessage], config: RunnableConfig
) -> AIMessage:
    """The model's reply to the conversation, asked once more when the provider flags the
    prompt; a second refusal, like every other failure, fails the turn."""
    try:
        reply = await bound.ainvoke(conversation, config)
    except Exception as error:
        if _PROMPT_FLAGGED not in str(error):
            raise
        log.warning("the provider flagged the prompt; sending it once more")
        reply = await bound.ainvoke(conversation, config)
    assert isinstance(reply, AIMessage), "a chat model answers with an AI message"
    return reply


def build_agent_graph(
    model: BaseChatModel,
    engine_tools: Sequence[BaseTool],
    tool_deps: ToolDeps,
    checkpointer: BaseCheckpointSaver[Any],
) -> AgentGraph:
    tools = [*engine_tools, *_check_model_tools(tool_deps)]
    bound = model.bind_tools(tools)

    async def call_model(state: MessagesState, config: RunnableConfig) -> MessagesState:
        configurable = config["configurable"]
        block = await turn_state(configurable[_USER_ID], configurable[_CHECK_ID], tool_deps)
        prefix = [SystemMessage(SYSTEM_PROMPT), SystemMessage(block)]
        conversation = [*prefix, *state["messages"]]
        reply = await _reply_of(bound, conversation, config)
        correction = _correction_for(reply, state["messages"], configurable[_CHECK_ID])
        if correction is not None:
            reply = await _reply_of(bound, [*conversation, reply, HumanMessage(correction)], config)
        _require_new_calls(reply, state["messages"])
        return {"messages": [reply]}

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=_tool_error_text))
    builder.add_node("refuse_nul", _refuse_nul)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", _after_model, ["tools", "refuse_nul", END])
    builder.add_edge("refuse_nul", "model")
    builder.add_conditional_edges("tools", _after_tools, ["model", END])
    return builder.compile(checkpointer=checkpointer)
