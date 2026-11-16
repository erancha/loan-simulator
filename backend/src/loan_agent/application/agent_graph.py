"""The agent loop: a language model leads the Hebrew conversation and calls the engine's tools and
the check tools until it has a reply for the person or has asked them a question through ask,
ask_term or ask_offer; each check's conversation is one checkpoint thread.

- build_agent_graph: the model node and the tool node over the thread's messages, as an AgentGraph
- check_config: the run configuration naming the person and the check, with the turn's step
  limit
- delete_conversation, copy_conversation: remove a check's saved conversation, or start
  another check's with its messages
- last_message: the last message of a check's conversation
- people_said: the texts of the person's own messages, whose English words a reply may repeat
- SYSTEM_PROMPT: the Hebrew instructions sent ahead of the messages on every model call, followed
  by the turn_state block of the check's stored loan, ceiling and finances
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
from langgraph.prebuilt import InjectedState, ToolNode, tools_condition
from pydantic import BaseModel, ConfigDict, Field, model_validator

from loan_agent.application.check_tools import (
    ChartSeries,
    CheckTools,
    ToolDeps,
    ToolError,
    english_words,
)
from loan_agent.application.turn_state import turn_state

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
_RECOMMENDATION_SECTION = re.compile(rf"^\W*{RECOMMENDATION_HEADING}\W*$", re.MULTILINE)
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


class LoanArgs(_Args):
    tracks: list[TrackArgs] = Field(min_length=1, description="The loan's tracks")


class SaveOptionArgs(_Args):
    loan: LoanArgs


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


class PresentRecommendationArgs(_Args):
    preferred_option_id: str = Field(description="option_id from save_option or save_offer")
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
        description="Two or more answers to pick from, in Hebrew; free questions only",
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

    async def save_option(loan: LoanArgs, config: RunnableConfig) -> str:
        return await _tools_for(config, deps).save_option(loan.model_dump(exclude_none=True))

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
            description="Show the term card: a term with its first payment, and a form with the "
            "term and the payment ceiling under one confirm button, and the turn ends; the answer "
            "arrives as the person's next message. Without term_months the card proposes the term.",
            args_schema=AskTermArgs,
        ),
        StructuredTool.from_function(
            coroutine=ask_offer,
            name="ask_offer",
            description="Call this when the person says they received a real offer and the "
            "message does not hold the lender, every track's interest and the number of months. "
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
            coroutine=save_option,
            name="save_option",
            description="Price an example track from suggest_tracks, for the check's loan "
            "amount, with the engine and keep it as an option of this check. Returns its "
            "option_id and figures. A real offer is saved with save_offer.",
            args_schema=SaveOptionArgs,
        ),
        StructuredTool.from_function(
            coroutine=save_offer,
            name="save_offer",
            description="Save a real offer the person received, with every track it names in "
            "one call: each track is priced for the check's loan amount and kept as an option "
            "of its own, and when one is refused none is saved. Returns each track's option_id "
            "and figures. With max_term_months a track is refused at any term but the one the "
            "engine's search over that track gives.",
            args_schema=SaveOfferArgs,
        ),
        StructuredTool.from_function(
            coroutine=present_recommendation,
            name="present_recommendation",
            description="Present the recommendation card: the preferred option and an optional "
            "alternative, with your reasoning. Without a ceiling the card says it is not yet "
            "checked against what the person can pay. Refused, with the reason and the remedy "
            "to offer, when a named option's worst-case payment is above the ceiling, when "
            "an example is preferred over a real offer, and when another option of the "
            "preferred one's kind and term fits and costs less in total.",
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
_QUESTION_TOOLS = frozenset({"ask", "ask_term", "ask_offer"})


def _require_one_question(state: MessagesState) -> None:
    if _question_call_count(state) > 1:
        raise ToolException(
            "one question per turn: call ask, ask_term or ask_offer once, with the one question to "
            "ask now"
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
    written without its tool, or English words the person did not write themselves, which are
    logged as a warning so their source can be found. A reply is redone once, whatever the
    second one says, so a turn never loops on a correction."""
    if _recommends_without_the_tool(reply, messages):
        return _REDO_THE_RECOMMENDATION
    english = english_words(reply.text, people_said(messages))
    if english:
        log.warning("reply rejected for English words %s in check %s", ", ".join(english), check_id)
        return _REWRITE_IN_HEBREW
    return None


def _after_tools(state: MessagesState) -> Literal["model", "__end__"]:
    """Ends the turn once ask, ask_term or ask_offer put a question on the person's screen; a
    refused question, like any other tool result, goes back to the model."""
    asked = _question_call_ids(state)
    for message in reversed(state["messages"]):
        if isinstance(message, AIMessage):
            break
        if (
            isinstance(message, ToolMessage)
            and message.tool_call_id in asked
            and message.status != "error"
        ):
            return "__end__"
    return "model"


def _tool_error_text(error: ToolError | ToolException) -> str:
    """The refusal or the engine's error, returned to the model as the tool's result so it can
    correct the call; ToolNode lets every other exception end the turn."""
    return str(error)


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
        reply = await bound.ainvoke(conversation, config)
        correction = _correction_for(reply, state["messages"], configurable[_CHECK_ID])
        if correction is not None:
            reply = await bound.ainvoke([*conversation, reply, HumanMessage(correction)], config)
        _require_new_calls(reply, state["messages"])
        return {"messages": [reply]}

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=_tool_error_text))
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition, ["tools", END])
    builder.add_conditional_edges("tools", _after_tools, ["model", END])
    return builder.compile(checkpointer=checkpointer)
