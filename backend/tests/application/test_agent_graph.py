"""The agent loop runs the model and its tools until the model answers, keeps each check's
conversation in checkpoints keyed by that check, and shows the model tool summaries only."""

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
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
from loan_agent.application.agent_graph import (
    RECOMMENDATION_HEADING,
    SYSTEM_PROMPT,
    SaveOptionArgs,
    TrackArgs,
    build_agent_graph,
    check_config,
)
from loan_agent.application.check_tools import ASKED_RESULT, ToolDeps
from loan_agent.domain.models import Check, Goal, OptionSource, Profile
from loan_agent.platform.checkpointer import checkpoint_serde
from loan_agent.ports.events import QUESTION_ASKED

PERSON = "1001"
CHECK = "check-1"
OTHER_PERSON = "2002"
OTHER_CHECK = "check-2"
SIMULATION_SUMMARY = "first_payment: 1887.99\nworst_peak_payment: 2038.63"
COMPLETE_FIGURES = {
    "net_fixed_income": "18000",
    "variable_income": "4000",
    "variable_income_minimum": "2000",
    "fixed_expenses": "9000",
    "existing_loan_payments": "800",
    "savings": "70000",
}
CHECK_TOOL_NAMES = {
    "update_profile",
    "set_goal",
    "save_option",
    "present_recommendation",
    "ask",
    "show_chart",
}


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
        Profile().merged(COMPLETE_FIGURES),
    )
    await world.checks.set_goal(CHECK, Goal("car", Decimal(120000)))
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
    assert [message.content for message in seen[2:]] == [
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
                        "user_id": OTHER_PERSON,
                        "check_id": OTHER_CHECK,
                    },
                )
            ),
            calls(("set_goal", {"purpose": "רכב", "price": "55000"})),
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
    assert (await world.checks.get(PERSON, CHECK)).goal == Goal("רכב", Decimal(55000))
    assert (await world.checks.get(OTHER_PERSON, OTHER_CHECK)).goal is None
    assert [event.check_id for event in world.sink.events] == [CHECK]


async def test_system_prompt_is_hebrew_and_first(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("שלום")])
    graph = run(world, model)

    await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))

    (seen,) = model.received
    assert isinstance(seen[0], SystemMessage)
    assert seen[0].content == SYSTEM_PROMPT
    assert isinstance(seen[1], SystemMessage)
    assert not [message for message in seen[2:] if isinstance(message, SystemMessage)]
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


def test_system_prompt_names_the_same_loan_sources_as_the_page() -> None:
    copy = (Path(__file__).parents[3] / "frontend/src/copy.ts").read_text(encoding="utf-8")
    match = re.search(r"OFFER_SOURCES = '(.+)'", copy)
    assert match is not None
    assert match[1] in SYSTEM_PROMPT


def test_every_tool_the_system_prompt_names_is_bound(world: World) -> None:
    def stand_in(name: str) -> BaseTool:
        async def engine_call() -> str:
            return ""

        return StructuredTool.from_function(coroutine=engine_call, name=name, description=name)

    model = ScriptedChatModel(replies=[])
    run(world, model, [stand_in(name) for name in sorted(ENGINE_TOOL_NAMES)])

    identifiers = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", SYSTEM_PROMPT))
    tool_fields = {*SaveOptionArgs.model_fields, *TrackArgs.model_fields}
    named_tools = identifiers - set(get_args(OptionSource)) - tool_fields
    assert "present_recommendation" in named_tools
    assert named_tools <= {tool.name for tool in model.tools}
    assert re.search(r"\bask\b", SYSTEM_PROMPT)
    assert "ask" in {tool.name for tool in model.tools}


async def test_ask_ends_the_turn_after_the_tool_node(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            AIMessage(
                content="כדי להעריך אני צריך כמה מספרים.",
                tool_calls=[
                    {
                        "name": "ask",
                        "args": {"question": {"field": "net_fixed_income"}},
                        "id": "call-ask-0",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage("never reached"),
        ]
    )
    graph = run(world, model)
    state = await graph.ainvoke(said("רוצה מכונית"), check_config(PERSON, CHECK))
    assert len(model.received) == 1
    assert isinstance(state["messages"][-1], ToolMessage)
    assert state["messages"][-1].content == ASKED_RESULT
    assert [e.type for e in world.sink.events] == [QUESTION_ASKED]
    assert world.sink.events[0].data == {
        "question": {"field": "net_fixed_income", "text": None, "choices": None},
        "lead_in": None,
    }


async def test_ask_schema_shown_to_the_model_hides_the_injected_state(world: World) -> None:
    model = ScriptedChatModel(replies=[])
    run(world, model)
    ask = next(tool for tool in model.tools if tool.name == "ask")
    assert set(ask.tool_call_schema.model_json_schema()["properties"]) == {"question", "lead_in"}


async def test_two_ask_calls_with_equal_ids_are_still_two_questions(world: World) -> None:
    def ask_call(field: str) -> Any:
        return {"name": "ask", "args": {"question": {"field": field}}, "id": "same"}

    twice = AIMessage(content="", tool_calls=[ask_call("savings"), ask_call("price")])
    model = ScriptedChatModel(replies=[twice, AIMessage("סליחה")])
    graph = run(world, model)
    await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    assert world.sink.events == []
    assert len(model.received) == 2


async def test_ask_ends_the_turn_even_when_a_sibling_call_fails(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(
                ("update_profile", {"savings": "-5"}),
                ("ask", {"question": {"field": "net_fixed_income"}}),
            ),
            AIMessage("never reached"),
        ]
    )
    graph = run(world, model)
    state = await graph.ainvoke(said("יש לי מינוס"), check_config(PERSON, CHECK))
    assert len(model.received) == 1
    results = tool_messages(state["messages"])
    assert {r.status for r in results} == {"error", "success"}


async def test_a_refused_ask_returns_to_the_model(world: World) -> None:
    await world.profiles.save(PERSON, Profile().merged({"savings": "12000"}))
    model = ScriptedChatModel(
        replies=[
            calls(("ask", {"question": {"field": "savings"}})),
            AIMessage("אז נמשיך"),
        ]
    )
    graph = run(world, model)
    state = await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    assert len(model.received) == 2
    assert state["messages"][-1].content == "אז נמשיך"


async def test_two_asks_in_one_message_are_both_refused(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(
                ("ask", {"question": {"field": "savings"}}),
                ("ask", {"question": {"field": "fixed_expenses"}}),
            ),
            AIMessage("אשאל אחת"),
        ]
    )
    graph = run(world, model)
    state = await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    assert all(r.status == "error" for r in tool_messages(state["messages"]))
    assert not [e for e in world.sink.events if e.type == QUESTION_ASKED]
    assert len(model.received) == 2


async def test_ask_schema_wants_exactly_one_of_field_and_text(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(("ask", {"question": {"field": "savings", "text": "כמה?"}})),
            calls(("ask", {"question": {"choices": ["כן"]}})),
            AIMessage("אתקן"),
        ]
    )
    graph = run(world, model)
    state = await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    assert all(r.status == "error" for r in tool_messages(state["messages"]))
    assert len(model.received) == 3


async def test_ask_refuses_an_empty_question_and_a_single_choice(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(("ask", {"question": {"text": ""}})),
            calls(("ask", {"question": {"text": "איזה רכב?", "choices": ["חדש"]}})),
            AIMessage("אתקן"),
        ]
    )
    graph = run(world, model)
    state = await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    empty, single = tool_messages(state["messages"])
    assert (empty.status, single.status) == ("error", "error")
    assert "text" in str(empty.content) and "choices" in str(single.content)
    assert not world.sink.events
    assert len(model.received) == 3


async def test_state_block_says_the_minimum_is_not_needed_without_variable_income(
    world: World,
) -> None:
    await world.profiles.save(PERSON, Profile().merged({"variable_income": "0"}))
    model = ScriptedChatModel(replies=[AIMessage("קיבלתי")])
    graph = run(world, model)
    await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    (seen,) = model.received
    block = seen[1].content
    assert "variable_income_minimum: not needed" in block
    assert "variable_income_minimum" not in block.split("missing:")[1].split("\n")[0]


async def test_state_block_carries_page_saved_figures_without_a_tool_call(world: World) -> None:
    await world.profiles.save(PERSON, Profile().merged({"net_fixed_income": "8000"}))
    await world.checks.set_goal(CHECK, Goal("מכונית", Decimal(60000)))
    model = ScriptedChatModel(replies=[AIMessage("קיבלתי")])
    graph = run(world, model)
    await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    (seen,) = model.received
    block = seen[1].content
    assert "net_fixed_income: 8000" in block
    assert "savings: not told" in block
    assert "missing:" in block and "savings" in block
    assert "מכונית" in block and "60000" in block


async def test_state_block_is_fresh_within_a_turn_and_never_checkpointed(world: World) -> None:
    model = ScriptedChatModel(
        replies=[calls(("update_profile", {"savings": "5000"})), AIMessage("נשמר")]
    )
    graph = run(world, model)
    config = check_config(PERSON, CHECK)
    state = await graph.ainvoke(said("יש לי 5000 בצד"), config)
    first, second = model.received
    assert "savings: not told" in first[1].content
    assert "savings: 5000" in second[1].content
    assert not [m for m in state["messages"] if isinstance(m, SystemMessage)]
    snapshot = await graph.aget_state(config)
    assert not [m for m in snapshot.values["messages"] if isinstance(m, SystemMessage)]


def recommendation_text() -> AIMessage:
    return AIMessage(f"**הנתונים**\nמטרה\n\n**{RECOMMENDATION_HEADING}**\nלקחת את ההלוואה")


async def test_a_recommendation_written_without_its_tool_is_redone_and_never_saved(
    world: World,
) -> None:
    model = ScriptedChatModel(replies=[recommendation_text(), AIMessage("אין עדיין המלצה")])
    graph = run(world, model)

    state = await graph.ainvoke(said("לקחת הלוואה"), check_config(PERSON, CHECK))

    assert len(model.received) == 2
    assert "present_recommendation" in model.received[1][-1].content
    assert [message.content for message in state["messages"]] == [
        "לקחת הלוואה",
        "אין עדיין המלצה",
    ]


async def test_a_recommendation_is_redone_only_once(world: World) -> None:
    model = ScriptedChatModel(replies=[recommendation_text(), recommendation_text()])
    graph = run(world, model)

    state = await graph.ainvoke(said("לקחת הלוואה"), check_config(PERSON, CHECK))

    assert len(model.received) == 2
    assert RECOMMENDATION_HEADING in state["messages"][-1].content


async def test_a_recommendation_from_an_earlier_turn_does_not_back_this_ones_text(
    world: World,
) -> None:
    await world.profiles.save(PERSON, Profile().merged(COMPLETE_FIGURES))
    await world.checks.set_goal(CHECK, Goal("car", Decimal(120000)))
    world.engine.simulations = [PRIME_SIMULATION]
    first = ScriptedChatModel(
        replies=[
            calls(("save_option", {"loan": {"tracks": [PRIME_TRACK]}, "source": "offer"})),
            calls(
                (
                    "present_recommendation",
                    {"preferred_option_id": "option-1", "reasoning": "בתוך התקרה"},
                )
            ),
            recommendation_text(),
        ]
    )
    await run(world, first).ainvoke(said("הצעה"), check_config(PERSON, CHECK))
    assert len(first.received) == 3, "this turn's call backs its own text"

    second = ScriptedChatModel(replies=[recommendation_text(), AIMessage("נמשיך")])
    await run(world, second).ainvoke(said("עוד אחת"), check_config(PERSON, CHECK))

    assert len(second.received) == 2


def test_the_recommendation_heading_is_the_one_the_system_prompt_asks_for() -> None:
    assert f"**{RECOMMENDATION_HEADING}**" in SYSTEM_PROMPT
