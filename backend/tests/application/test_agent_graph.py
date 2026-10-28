"""The agent loop runs the model and its tools until the model answers, keeps each check's
conversation in checkpoints keyed by that check, and shows the model tool summaries only."""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, get_args

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langgraph.checkpoint.memory import InMemorySaver

from fakes import (
    ENGINE_TOOL_NAMES,
    NOW,
    PRIME_SIMULATION,
    PRIME_TRACK,
    Clock,
    FakeLoanEngine,
    Ids,
    InMemoryCheckRepository,
    InMemoryOptionRepository,
    InMemoryProfileRepository,
    InMemoryRecommendationRepository,
    RecordingSink,
    ScriptedChatModel,
    engine_fixture,
)
from loan_agent.application.agent_graph import SYSTEM_PROMPT, build_agent_graph, check_config
from loan_agent.application.check_tools import ToolDeps
from loan_agent.domain.models import Check, Goal, OptionSource, Profile
from loan_agent.platform.checkpointer import checkpoint_serde

PERSON = "1001"
CHECK = "check-1"
OTHER_PERSON = "2002"
OTHER_CHECK = "check-2"
SIMULATION_SUMMARY = "first_payment: 1887.99\nworst_peak_payment: 2038.63"
CHECK_TOOL_NAMES = {"update_profile", "set_goal", "save_option", "present_recommendation"}


@dataclass
class World:
    profiles: InMemoryProfileRepository
    checks: InMemoryCheckRepository
    options: InMemoryOptionRepository
    recommendations: InMemoryRecommendationRepository
    engine: FakeLoanEngine
    sink: RecordingSink
    deps: ToolDeps
    saver: InMemorySaver


@pytest.fixture
async def world() -> World:
    clock = Clock()
    profiles = InMemoryProfileRepository(clock)
    checks = InMemoryCheckRepository()
    options = InMemoryOptionRepository()
    recommendations = InMemoryRecommendationRepository()
    engine = FakeLoanEngine()
    sink = RecordingSink()
    await checks.add(Check(CHECK, PERSON, NOW, None, None))
    await checks.add(Check(OTHER_CHECK, OTHER_PERSON, NOW, None, None))
    deps = ToolDeps(
        profiles=profiles,
        checks=checks,
        options=options,
        recommendations=recommendations,
        engine=engine,
        sink=sink,
        clock=clock,
        new_id=Ids("option"),
    )
    return World(
        profiles,
        checks,
        options,
        recommendations,
        engine,
        sink,
        deps,
        InMemorySaver(serde=checkpoint_serde()),
    )


def fake_simulate_loan() -> BaseTool:
    """Stands in for the engine's MCP tool: the model reads the summary; the full result rides
    along as the tool message's artifact, which the model never sees."""

    async def simulate_loan(loan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return SIMULATION_SUMMARY, engine_fixture("simulate_loan_unlinked_prime")

    return StructuredTool.from_function(
        coroutine=simulate_loan,
        name="simulate_loan",
        description="Simulate a loan",
        response_format="content_and_artifact",
    )


def failing_engine_tool(error: Exception) -> BaseTool:
    async def size_loan(goal_price: str) -> str:
        raise error

    return StructuredTool.from_function(
        coroutine=size_loan, name="size_loan", description="Size the loan"
    )


def calls(*tool_calls: tuple[str, dict[str, Any]]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call-{name}-{index}", "type": "tool_call"}
            for index, (name, args) in enumerate(tool_calls)
        ],
    )


def run(world: World, model: ScriptedChatModel, engine_tools: list[BaseTool] | None = None) -> Any:
    return build_agent_graph(
        model,
        engine_tools=[fake_simulate_loan()] if engine_tools is None else engine_tools,
        tool_deps=world.deps,
        checkpointer=world.saver,
    )


def said(text: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(text)]}


def tool_messages(messages: list[Any]) -> list[ToolMessage]:
    return [message for message in messages if isinstance(message, ToolMessage)]


async def test_tool_call_runs_and_model_sees_summary_only(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(("simulate_loan", {"loan": {"tracks": [PRIME_TRACK]}})),
            AIMessage("ההחזר החודשי הוא כ-1,888 ₪"),
        ]
    )
    graph = run(world, model)

    state = await graph.ainvoke(said("כמה אשלם?"), check_config(PERSON, CHECK))

    (result,) = tool_messages(state["messages"])
    assert result.content == SIMULATION_SUMMARY
    assert result.artifact["tracks"][0]["schedule"], "the page still receives the schedule"
    assert len(model.received) == 2
    seen = [message.content for message in model.received[1]]
    assert SIMULATION_SUMMARY in seen
    assert not [content for content in seen if "schedule" in str(content)]
    assert state["messages"][-1].content == "ההחזר החודשי הוא כ-1,888 ₪"


async def test_guardrail_refusal_reaches_model_which_retries(world: World) -> None:
    await world.profiles.save(
        PERSON,
        Profile().merged(
            {
                "net_fixed_income": "18000",
                "variable_income": "4000",
                "variable_income_stable": True,
                "fixed_expenses": "9000",
                "existing_loan_payments": "800",
                "savings": "70000",
            }
        ),
    )
    await world.checks.set_goal(CHECK, Goal("car", Decimal(160000), Decimal(40000)))
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION]
    short_track = {**PRIME_TRACK, "principal": "70000"}
    model = ScriptedChatModel(
        replies=[
            calls(
                ("save_option", {"loan": {"tracks": [short_track]}, "source": "published_average"}),
                ("save_option", {"loan": {"tracks": [PRIME_TRACK]}, "source": "published_average"}),
            ),
            calls(
                (
                    "present_recommendation",
                    {"preferred_option_id": "option-1", "reasoning": "הזול ביותר"},
                )
            ),
            calls(
                (
                    "present_recommendation",
                    {"preferred_option_id": "option-2", "reasoning": "בתוך התקרה"},
                )
            ),
            AIMessage("ההמלצה מוכנה"),
        ]
    )
    graph = run(world, model)

    state = await graph.ainvoke(said("מה ההמלצה?"), check_config(PERSON, CHECK))

    refusal, accepted = tool_messages(state["messages"])[2:]
    assert refusal.status == "error"
    assert "below the loan_amount of 80000.00" in str(refusal.content)
    assert refusal in model.received[2]
    assert accepted.status == "success"
    recommendation = await world.recommendations.latest(CHECK)
    assert recommendation is not None
    assert recommendation.preferred_option_id == "option-2"
    assert state["messages"][-1].content == "ההמלצה מוכנה"


async def test_thread_resumes_from_checkpoint(world: World) -> None:
    first = ScriptedChatModel(replies=[AIMessage("שלום! למה ההלוואה?")])
    await run(world, first).ainvoke(said("שלום"), check_config(PERSON, CHECK))

    # A graph built afresh on the same saver stands in for a later visit after a restart.
    second = ScriptedChatModel(replies=[AIMessage("רכב ב-55 אלף, הבנתי")])
    await run(world, second).ainvoke(said("לרכב"), check_config(PERSON, CHECK))

    (seen,) = second.received
    assert [message.content for message in seen[1:]] == [
        "שלום",
        "שלום! למה ההלוואה?",
        "לרכב",
    ]


async def test_model_cannot_choose_user_or_check(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(
                (
                    "set_goal",
                    {
                        "purpose": "רכב",
                        "price": "55000",
                        "trade_in_value": "20000",
                        "user_id": OTHER_PERSON,
                        "check_id": OTHER_CHECK,
                    },
                )
            ),
            calls(("set_goal", {"purpose": "רכב", "price": "55000", "trade_in_value": "20000"})),
            AIMessage("נשמר"),
        ]
    )
    graph = run(world, model)

    state = await graph.ainvoke(said("רכב ב-55 אלף"), check_config(PERSON, CHECK))

    for tool in model.tools:
        if tool.name in CHECK_TOOL_NAMES:
            properties = tool.tool_call_schema.model_json_schema()["properties"]
            assert not {"user_id", "check_id", "thread_id"} & set(properties)
    smuggled, saved = tool_messages(state["messages"])
    assert smuggled.status == "error"
    assert saved.status == "success"
    assert (await world.checks.get(PERSON, CHECK)).goal == Goal(
        "רכב", Decimal(55000), Decimal(20000)
    )
    assert (await world.checks.get(OTHER_PERSON, OTHER_CHECK)).goal is None
    assert [event.check_id for event in world.sink.events] == [CHECK]


async def test_system_prompt_is_hebrew_and_first(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("שלום")])
    graph = run(world, model)

    await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))

    (seen,) = model.received
    assert isinstance(seen[0], SystemMessage)
    assert seen[0].content == SYSTEM_PROMPT
    assert not [message for message in seen[1:] if isinstance(message, SystemMessage)]
    letters = re.findall(r"[^\W\d_]", SYSTEM_PROMPT)
    hebrew = re.findall(r"[א-ת]", SYSTEM_PROMPT)
    assert len(hebrew) > 0.8 * len(letters)


async def test_model_is_bound_to_engine_and_check_tools(world: World) -> None:
    model = ScriptedChatModel(replies=[])
    run(world, model)

    assert {tool.name for tool in model.tools} == {"simulate_loan", *CHECK_TOOL_NAMES}


async def test_save_option_schema_types_money_as_decimal_strings(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(
                (
                    "save_option",
                    {
                        "loan": {"tracks": [{**PRIME_TRACK, "principal": 80000.5}]},
                        "source": "offer",
                    },
                )
            ),
            AIMessage("אתקן"),
        ]
    )
    graph = run(world, model)

    state = await graph.ainvoke(said("הצעה מהבנק"), check_config(PERSON, CHECK))

    (refusal,) = tool_messages(state["messages"])
    assert refusal.status == "error"
    assert "principal" in str(refusal.content)
    assert world.engine.calls == []


async def test_engine_tool_error_reaches_model(world: World) -> None:
    model = ScriptedChatModel(
        replies=[calls(("size_loan", {"goal_price": "-1"})), AIMessage("אבדוק שוב")]
    )
    graph = run(world, model, [failing_engine_tool(ToolException("goal_price must be >= 0"))])

    state = await graph.ainvoke(said("כמה ללוות?"), check_config(PERSON, CHECK))

    (error,) = tool_messages(state["messages"])
    assert error.content == "goal_price must be >= 0"
    assert error in model.received[1]


async def test_unexpected_tool_failure_ends_the_turn(world: World) -> None:
    model = ScriptedChatModel(replies=[calls(("size_loan", {"goal_price": "1"}))])
    graph = run(world, model, [failing_engine_tool(RuntimeError("engine unreachable"))])

    with pytest.raises(RuntimeError, match="engine unreachable"):
        await graph.ainvoke(said("כמה ללוות?"), check_config(PERSON, CHECK))


def test_every_tool_the_system_prompt_names_is_bound(world: World) -> None:
    def stand_in(name: str) -> BaseTool:
        async def engine_call() -> str:
            return ""

        return StructuredTool.from_function(coroutine=engine_call, name=name, description=name)

    model = ScriptedChatModel(replies=[])
    run(world, model, [stand_in(name) for name in sorted(ENGINE_TOOL_NAMES)])

    identifiers = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", SYSTEM_PROMPT))
    named_tools = identifiers - set(get_args(OptionSource))
    assert "present_recommendation" in named_tools
    assert named_tools <= {tool.name for tool in model.tools}
