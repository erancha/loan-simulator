"""The agent loop: a language model leads the Hebrew conversation and calls the engine's tools and
the check tools until it has a reply for the person; each check's conversation is one checkpoint
thread.

- build_agent_graph: the model node and the tool node over the thread's messages, as an AgentGraph
- check_config: the run configuration naming the person and the check, with the turn's step
  limit
- SYSTEM_PROMPT: the Hebrew instructions sent ahead of the messages on every model call
- The check tools' argument schemas, with money as decimal strings like the engine's own schema

The person and the check come from the run configuration, never from the model's arguments, so
the model can only act on the check it is talking about.
"""

from collections.abc import Sequence
from importlib.resources import files
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, ConfigDict, Field

from loan_agent.application.check_tools import CheckTools, ToolDeps, ToolError
from loan_agent.domain.models import OptionSource

SYSTEM_PROMPT = (files(__package__) / "prompts" / "system_he.md").read_text(encoding="utf-8")

# The graph steps one turn may take before it fails; a model call is one step, and the tool calls
# it asks for, run together, are one more. A first recommendation takes about 13 steps, so the
# limit stops a model that keeps calling tools after about 20 model calls; the per-person message
# cap (Settings.agent_turn_limit) bounds messages, not the model calls inside one.
TURN_STEP_LIMIT = 40

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


class UpdateProfileArgs(_Args):
    net_fixed_income: str | None = _optional_money(
        "Fixed income after tax, from the payslip, ₪ per month"
    )
    variable_income: str | None = _optional_money(
        "Income that varies (tips, bonuses, freelance work), net, ₪ per month on average"
    )
    variable_income_stable: bool | None = Field(
        default=None,
        description="true when the variable income is steady month to month; omit when not told",
    )
    fixed_expenses: str | None = _optional_money(
        "Rent, bills and other recurring spending, ₪ per month"
    )
    existing_loan_payments: str | None = _optional_money(
        "Payments on loans already running, ₪ per month"
    )
    savings: str | None = _optional_money("Total savings, ₪ (an amount, not per month)")


class SetGoalArgs(_Args):
    purpose: str = Field(description="What the loan is for, in the person's words")
    price: str = _money("Price of the purchase, ₪")
    trade_in_value: str = _money("Value of what the person trades in, ₪; '0' if nothing")


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
        description="Annual percent over prime ('1.5' means prime + 1.5%), as a decimal string; "
        "prime tracks only",
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
    source: OptionSource = Field(
        description="'published_average' for a track priced from the Bank of Israel average "
        "(suggest_tracks), 'offer' for a real offer the person received"
    )
    lender: str | None = Field(default=None, description="Who made the offer; offers only")
    offer_date: str | None = Field(
        default=None, description="Date of the offer, ISO like 2026-10-20; offers only"
    )


class PresentRecommendationArgs(_Args):
    preferred_option_id: str = Field(description="option_id from save_option")
    reasoning: str = Field(description="Why this option fits the person, in Hebrew")
    alternative_option_id: str | None = Field(
        default=None, description="option_id of a second choice, if any"
    )


AgentGraph = CompiledStateGraph[MessagesState, None, MessagesState, MessagesState]


def check_config(user_id: str, check_id: str) -> RunnableConfig:
    return {
        "configurable": {_USER_ID: user_id, _CHECK_ID: check_id},
        "recursion_limit": TURN_STEP_LIMIT,
    }


def _tools_for(config: RunnableConfig, deps: ToolDeps) -> CheckTools:
    configurable = config["configurable"]
    return CheckTools(configurable[_USER_ID], configurable[_CHECK_ID], deps)


def _check_model_tools(deps: ToolDeps) -> list[BaseTool]:
    async def update_profile(config: RunnableConfig, **fields: object) -> str:
        told = {name: value for name, value in fields.items() if value is not None}
        return await _tools_for(config, deps).update_profile(**told)

    async def set_goal(
        purpose: str, price: str, trade_in_value: str, config: RunnableConfig
    ) -> str:
        return await _tools_for(config, deps).set_goal(purpose, price, trade_in_value)

    async def save_option(
        loan: LoanArgs,
        source: str,
        config: RunnableConfig,
        lender: str | None = None,
        offer_date: str | None = None,
    ) -> str:
        return await _tools_for(config, deps).save_option(
            loan.model_dump(exclude_none=True), source, lender, offer_date
        )

    async def present_recommendation(
        preferred_option_id: str,
        reasoning: str,
        config: RunnableConfig,
        alternative_option_id: str | None = None,
    ) -> str:
        return await _tools_for(config, deps).present_recommendation(
            preferred_option_id, reasoning, alternative_option_id
        )

    return [
        StructuredTool.from_function(
            coroutine=update_profile,
            name="update_profile",
            description="Save what the person told about their finances. Send only the fields "
            "they told or corrected; every amount is net, in ₪. Returns the whole profile and "
            "what is still missing.",
            args_schema=UpdateProfileArgs,
        ),
        StructuredTool.from_function(
            coroutine=set_goal,
            name="set_goal",
            description="Save what the person wants to buy and its price. The loan amount is "
            "derived later by size_loan.",
            args_schema=SetGoalArgs,
        ),
        StructuredTool.from_function(
            coroutine=save_option,
            name="save_option",
            description="Price a loan with the engine and keep it as an option of this check. "
            "Returns its option_id and figures.",
            args_schema=SaveOptionArgs,
        ),
        StructuredTool.from_function(
            coroutine=present_recommendation,
            name="present_recommendation",
            description="Present the recommendation card: the preferred option and an optional "
            "alternative, with your reasoning. Refused, with the reason, when an option is "
            "outside the engine's bounds.",
            args_schema=PresentRecommendationArgs,
        ),
    ]


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
        reply = await bound.ainvoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]], config)
        return {"messages": [reply]}

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=_tool_error_text))
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition, ["tools", END])
    builder.add_edge("tools", "model")
    return builder.compile(checkpointer=checkpointer)
