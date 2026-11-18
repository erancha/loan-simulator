"""The agent loop runs the model and its tools until the model answers, keeps each check's
conversation in checkpoints keyed by that check, and shows the model tool summaries only."""

import logging
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langgraph.checkpoint.memory import InMemorySaver

from fakes import (
    BALLOON_SIMULATION,
    LEUMI_READINGS,
    NOW,
    PRIME_SIMULATION,
    PRIME_TRACK,
    Clock,
    FakeLoanEngine,
    Ids,
    InMemoryAwaitingOfferRepository,
    InMemoryCheckRepository,
    InMemoryOptionRepository,
    InMemoryRecommendationRepository,
    RecordingSink,
    ScriptedChatModel,
    awaiting_offer,
    engine_fixture,
)
from loan_agent.adapters.engine_mcp import MODEL_ENGINE_TOOLS
from loan_agent.application.agent_graph import (
    EVALUATION_HEADING,
    RECOMMENDATION_HEADING,
    SYSTEM_PROMPT,
    AskArgs,
    AskOfferArgs,
    AskQuestion,
    AskTermArgs,
    OfferTrackArgs,
    PresentRecommendationArgs,
    QuestionField,
    ReadOfferArgs,
    SetCeilingArgs,
    SetLoanArgs,
    SetTermArgs,
    TrackArgs,
    UpdateFinancesArgs,
    _after_tools,
    build_agent_graph,
    check_config,
)
from loan_agent.application.check_tools import ASKED_RESULT, READING_ON_SCREEN, ToolDeps
from loan_agent.application.turn_state import turn_state
from loan_agent.domain.models import (
    Check,
    Finances,
    LoanRequest,
    OptionSource,
    Recommendation,
)
from loan_agent.platform.checkpointer import checkpoint_serde
from loan_agent.ports.events import (
    OFFER_AWAITING,
    OFFER_DROPPED,
    OFFER_IDENTIFIED,
    OFFER_SETTLED,
    QUESTION_ASKED,
)

PERSON = "1001"
CHECK = "check-1"
OTHER_PERSON = "2002"
OTHER_CHECK = "check-2"
SIMULATION_SUMMARY = "first_payment: 1887.99\nworst_peak_payment: 2038.63"
CHECK_TOOL_NAMES = {
    "set_loan",
    "ask_term",
    "compare_terms",
    "ask_offer",
    "set_term",
    "set_ceiling",
    "update_finances",
    "save_examples",
    "save_offer",
    "read_offer",
    "answer_offer_amount",
    "present_recommendation",
    "ask",
    "show_chart",
}


@dataclass
class World:
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
    checks = InMemoryCheckRepository()
    options = InMemoryOptionRepository()
    recommendations = InMemoryRecommendationRepository()
    engine = FakeLoanEngine()
    sink = RecordingSink()
    await checks.add(Check(CHECK, PERSON, NOW, None, None, None, None, Finances()))
    await checks.add(Check(OTHER_CHECK, OTHER_PERSON, NOW, None, None, None, None, Finances()))
    deps = ToolDeps(
        checks=checks,
        options=options,
        awaiting=InMemoryAwaitingOfferRepository(),
        recommendations=recommendations,
        engine=engine,
        sink=sink,
        clock=clock,
        new_id=Ids("option"),
    )
    return World(
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
    async def suggest_tracks(principal: str) -> str:
        raise error

    return StructuredTool.from_function(
        coroutine=suggest_tracks, name="suggest_tracks", description="Suggest tracks"
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
    await world.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(80000)))
    await world.checks.set_term(CHECK, 48)
    await world.checks.set_ceiling(CHECK, Decimal(1500), "stated")
    # The three examples, the third above the ceiling like the first; the last prices the
    # accepted option at the shorter term the engine's search finds.
    above = replace(PRIME_SIMULATION.figures, worst_peak_payment=Decimal(2100))
    world.engine.simulations = [
        PRIME_SIMULATION,
        BALLOON_SIMULATION,
        replace(PRIME_SIMULATION, figures=above),
        BALLOON_SIMULATION,
    ]
    model = ScriptedChatModel(
        replies=[
            calls(("save_examples", {})),
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

    refusal, accepted = tool_messages(state["messages"])[1:]
    assert refusal.status == "error"
    assert "above the payment_ceiling of 1500" in str(refusal.content)
    assert "option option-2 fits" in str(refusal.content)
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
                    "set_loan",
                    {
                        "purpose": "רכב",
                        "amount": "55000",
                        "user_id": OTHER_PERSON,
                        "check_id": OTHER_CHECK,
                    },
                )
            ),
            calls(("set_loan", {"purpose": "רכב", "amount": "55000"})),
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
    assert (await world.checks.get(PERSON, CHECK)).loan == LoanRequest("רכב", Decimal(55000))
    assert (await world.checks.get(OTHER_PERSON, OTHER_CHECK)).loan is None
    assert [event.check_id for event in world.sink.events] == [CHECK]


FLAGGED = RuntimeError(
    "Invalid prompt: your prompt was flagged as potentially violating our usage policy."
)


async def test_a_prompt_the_provider_flags_is_sent_once_more(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("שלום")], errors=[FLAGGED])

    result = await run(world, model).ainvoke(said("שלום"), check_config(PERSON, CHECK))

    assert result["messages"][-1].content == "שלום"
    first, second = model.received
    assert first == second


async def test_a_prompt_flagged_twice_fails_the_turn(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("שלום")], errors=[FLAGGED, FLAGGED])

    with pytest.raises(RuntimeError, match="flagged"):
        await run(world, model).ainvoke(said("שלום"), check_config(PERSON, CHECK))


async def test_another_provider_error_is_not_retried(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("שלום")], errors=[RuntimeError("rate limited")])

    with pytest.raises(RuntimeError, match="rate limited"):
        await run(world, model).ainvoke(said("שלום"), check_config(PERSON, CHECK))
    assert len(model.received) == 1


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


async def test_save_offer_schema_types_money_as_decimal_strings(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(
                (
                    "save_offer",
                    {"tracks": [{**PRIME_TRACK, "principal": 80000.5}]},
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
        replies=[calls(("suggest_tracks", {"principal": "-1"})), AIMessage("אבדוק שוב")]
    )
    graph = run(world, model, [failing_engine_tool(ToolException("principal must be >= 0"))])

    state = await graph.ainvoke(said("כמה ללוות?"), check_config(PERSON, CHECK))

    (error,) = tool_messages(state["messages"])
    assert error.content == "principal must be >= 0"
    assert error in model.received[1]


async def test_tool_call_holding_a_nul_character_is_refused_before_it_runs(world: World) -> None:
    model = ScriptedChatModel(
        replies=[calls(("suggest_tracks", {"principal": "1\x00"})), AIMessage("אשלח שוב")]
    )
    graph = run(world, model, [failing_engine_tool(RuntimeError("the tool ran"))])

    state = await graph.ainvoke(said("כמה ללוות?"), check_config(PERSON, CHECK))

    (refusal,) = tool_messages(state["messages"])
    assert refusal.status == "error"
    assert "NUL" in str(refusal.content)
    assert refusal in model.received[1]


async def test_unexpected_tool_failure_ends_the_turn(world: World) -> None:
    model = ScriptedChatModel(replies=[calls(("suggest_tracks", {"principal": "1"}))])
    graph = run(world, model, [failing_engine_tool(RuntimeError("engine unreachable"))])

    with pytest.raises(RuntimeError, match="engine unreachable"):
        await graph.ainvoke(said("כמה ללוות?"), check_config(PERSON, CHECK))


def test_system_prompt_names_the_same_loan_sources_as_the_page() -> None:
    copy = (Path(__file__).parents[3] / "frontend/src/copy.ts").read_text(encoding="utf-8")
    match = re.search(r"OFFER_SOURCES = '(.+)'", copy)
    assert match is not None
    assert match[1] in SYSTEM_PROMPT


def test_system_prompt_names_the_same_purpose_choices_as_the_page() -> None:
    copy = (Path(__file__).parents[3] / "frontend/src/check/copy.ts").read_text(encoding="utf-8")
    match = re.search(r"PURPOSE_CHOICES = \[(.+)\]", copy)
    assert match is not None
    choices = re.findall(r"'([^']+)'", match[1])
    assert choices
    assert ", ".join(f"'{choice}'" for choice in choices) in SYSTEM_PROMPT


def test_system_prompt_and_track_schema_say_a_margin_under_prime_is_negative() -> None:
    assert "פריים מינוס" in SYSTEM_PROMPT
    assert "-0.25" in str(TrackArgs.model_fields["prime_spread"].description)


async def test_every_tool_the_system_prompt_names_is_bound(world: World) -> None:
    def stand_in(name: str) -> BaseTool:
        async def engine_call() -> str:
            return ""

        return StructuredTool.from_function(coroutine=engine_call, name=name, description=name)

    model = ScriptedChatModel(replies=[])
    run(world, model, [stand_in(name) for name in sorted(MODEL_ENGINE_TOOLS)])

    identifiers = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", SYSTEM_PROMPT))
    tool_fields = {
        *SetLoanArgs.model_fields,
        *AskTermArgs.model_fields,
        *AskOfferArgs.model_fields,
        *OfferTrackArgs.model_fields,
        *SetTermArgs.model_fields,
        *SetCeilingArgs.model_fields,
        *UpdateFinancesArgs.model_fields,
        *TrackArgs.model_fields,
        *AskQuestion.model_fields,
        *AskArgs.model_fields,
        *PresentRecommendationArgs.model_fields,
        *ReadOfferArgs.model_fields,
    }
    state_keys = {
        line.split(":")[0] for line in (await turn_state(PERSON, CHECK, world.deps)).splitlines()
    }
    # Keys of a tool's result that the prompt tells the model how to use.
    result_keys = {
        "preferred_ceiling_margin",
        "alternative_ceiling_margin",
        "payment_changes",
        "preferred_figures",
        "alternative_figures",
        "preferred_price",
        "alternative_price",
        "only_option",
        "interest_cost",
        "rate_today",
    }
    named_tools = (
        (identifiers - set(get_args(OptionSource)) - set(get_args(QuestionField)) - tool_fields)
        - state_keys
        - result_keys
    )
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
        "question": {
            "field": "net_fixed_income",
            "text": None,
            "choices": None,
            "offer_clone": False,
        },
        "lead_in": None,
    }


async def test_ask_offer_ends_the_turn_with_the_form_on_the_screen(world: World) -> None:
    await world.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(60000)))
    track = {"rate_kind": "prime", "rate": "0.5", "cpi_linked": False}
    model = ScriptedChatModel(
        replies=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_offer",
                        "args": {"lender": "קרן הפנסיה", "tracks": [track]},
                        "id": "call-offer-0",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage("never reached"),
        ]
    )
    graph = run(world, model)
    state = await graph.ainvoke(said("קיבלתי הצעה מקרן הפנסיה"), check_config(PERSON, CHECK))
    assert len(model.received) == 1
    assert state["messages"][-1].content == ASKED_RESULT
    assert world.sink.events[-1].data == {
        "question": {
            "kind": "offer",
            "lender": "קרן הפנסיה",
            "tracks": [track],
            "max_term_months": None,
        },
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

    twice = AIMessage(
        content="", tool_calls=[ask_call("net_fixed_income"), ask_call("fixed_expenses")]
    )
    model = ScriptedChatModel(replies=[twice, AIMessage("סליחה")])
    graph = run(world, model)
    await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    assert world.sink.events == []
    assert len(model.received) == 2


async def test_ask_ends_the_turn_even_when_a_sibling_call_fails(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(
                ("update_finances", {"net_fixed_income": "-5"}),
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
    await world.checks.set_finances(CHECK, Finances(net_fixed_income=Decimal(12000)))
    model = ScriptedChatModel(
        replies=[
            calls(("ask", {"question": {"field": "net_fixed_income"}})),
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
                ("ask", {"question": {"field": "net_fixed_income"}}),
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
            calls(("ask", {"question": {"field": "amount", "text": "כמה?"}})),
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


async def test_ask_offers_a_clone_only_after_a_recommendation(world: World) -> None:
    offer = ("ask", {"question": {"offer_clone": True}})
    model = ScriptedChatModel(replies=[calls(offer), AIMessage("אין עוד המלצה")])
    graph = run(world, model)
    state = await graph.ainvoke(said("ומה עם 1,000 בחודש?"), check_config(PERSON, CHECK))
    assert tool_messages(state["messages"])[0].status == "error"
    assert not world.sink.events

    await world.recommendations.save(Recommendation(CHECK, "o1", None, "כי", Decimal(1), None, NOW))
    model.replies.append(calls(offer))
    await graph.ainvoke(said("ומה עם 1,000 בחודש?"), check_config(PERSON, CHECK))
    assert [e.data for e in world.sink.events] == [
        {
            "question": {"field": None, "text": None, "choices": None, "offer_clone": True},
            "lead_in": None,
        }
    ]


async def test_ask_schema_keeps_a_clone_offer_free_of_field_text_and_choices(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            calls(("ask", {"question": {"offer_clone": True, "text": "לשכפל?"}})),
            AIMessage("אתקן"),
        ]
    )
    graph = run(world, model)
    state = await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    assert tool_messages(state["messages"])[0].status == "error"


async def test_state_block_carries_page_saved_figures_without_a_tool_call(world: World) -> None:
    await world.checks.set_finances(CHECK, Finances(net_fixed_income=Decimal(8000)))
    await world.checks.set_loan(CHECK, LoanRequest("מכונית", Decimal(60000)))
    model = ScriptedChatModel(replies=[AIMessage("קיבלתי")])
    graph = run(world, model)
    await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))
    (seen,) = model.received
    block = seen[1].content
    assert "net_fixed_income: 8000" in block
    assert "fixed_expenses: not told" in block
    assert "missing: fixed_expenses" in block
    assert "מכונית" in block and "60000" in block


async def test_state_block_is_fresh_within_a_turn_and_never_checkpointed(world: World) -> None:
    model = ScriptedChatModel(
        replies=[calls(("update_finances", {"net_fixed_income": "5000"})), AIMessage("נשמר")]
    )
    graph = run(world, model)
    config = check_config(PERSON, CHECK)
    state = await graph.ainvoke(said("אני מרוויח 5000 נטו"), config)
    first, second = model.received
    assert "net_fixed_income: not told" in first[1].content
    assert "net_fixed_income: 5000" in second[1].content
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


async def test_an_evaluation_of_one_offer_written_without_its_tool_is_redone(
    world: World,
) -> None:
    evaluation = AIMessage(f"**{EVALUATION_HEADING}**\nההצעה של לאומי")
    model = ScriptedChatModel(replies=[evaluation, AIMessage("עוד אין הצעה")])
    graph = run(world, model)

    state = await graph.ainvoke(said("הצעה"), check_config(PERSON, CHECK))

    assert len(model.received) == 2
    assert "present_recommendation" in model.received[1][-1].content
    assert state["messages"][-1].content == "עוד אין הצעה"


async def test_a_recommendation_is_redone_only_once(world: World) -> None:
    model = ScriptedChatModel(replies=[recommendation_text(), recommendation_text()])
    graph = run(world, model)

    state = await graph.ainvoke(said("לקחת הלוואה"), check_config(PERSON, CHECK))

    assert len(model.received) == 2
    assert RECOMMENDATION_HEADING in state["messages"][-1].content


async def test_a_recommendation_from_an_earlier_turn_does_not_back_this_ones_text(
    world: World,
) -> None:
    await world.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(80000)))
    world.engine.simulations = [PRIME_SIMULATION]
    first = ScriptedChatModel(
        replies=[
            calls(("save_offer", {"tracks": [PRIME_TRACK]})),
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
    assert f"**{EVALUATION_HEADING}**" in SYSTEM_PROMPT


def test_the_prompt_orders_a_track_as_payment_then_price_then_history() -> None:
    """A track's lines open with what the person pays: today's payment, then the interest ahead
    of the total it adds up to, and the historical period last."""
    flat = " ".join(SYSTEM_PROMPT.split())
    payment = flat.index('בשורה הראשונה "החזר היום: X ₪"')
    price = flat.index('"ריבית של כ-4,988 ₪; סכום כולל להחזר: 49,988 ₪ (45,000 + 4,988)"')
    history = flat.index("ובשורה האחרונה ההחזר בתקופה ההיסטורית הגרועה")
    assert payment < price < history


def test_the_prompt_names_examples_only_by_the_counts_and_prices_every_offer() -> None:
    assert "option_counts" in SYSTEM_PROMPT
    for key in ("interest_cost", "rate_today", "preferred_price", "only_option"):
        assert key in SYSTEM_PROMPT, key
    assert "מתחת לתקרה" in SYSTEM_PROMPT


async def test_a_reply_with_an_english_word_is_rewritten_once(world: World) -> None:
    model = ScriptedChatModel(
        replies=[
            AIMessage("מטרה: מכונית, price: 50,000 ₪"),
            AIMessage("מטרה: מכונית, מחיר 50,000 ₪"),
        ]
    )
    graph = run(world, model)

    state = await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))

    assert len(model.received) == 2
    assert "English" in model.received[1][-1].content
    assert state["messages"][-1].content == "מטרה: מכונית, מחיר 50,000 ₪"


async def test_a_reply_holding_a_nul_character_is_rewritten(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("מטרה: מכו\x00נית"), AIMessage("מטרה: מכונית")])
    graph = run(world, model)

    state = await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))

    assert "NUL" in model.received[1][-1].content
    assert [message.content for message in state["messages"][1:]] == ["מטרה: מכונית"]


async def test_an_english_word_is_rewritten_only_once(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("price: 1"), AIMessage("price: 1")])
    graph = run(world, model)

    state = await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))

    assert len(model.received) == 2
    assert state["messages"][-1].content == "price: 1"


async def test_an_english_name_the_person_wrote_stands(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("קיבלתי הצעה מ-Max")])
    graph = run(world, model)

    await graph.ainvoke(said("הצעה מ-Max"), check_config(PERSON, CHECK))

    assert len(model.received) == 1


async def test_a_rewritten_reply_is_logged_as_a_warning_naming_its_english_words(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    model = ScriptedChatModel(
        replies=[AIMessage("ההפרש slight, price 3"), AIMessage("ההפרש במקצת, מחיר 3")]
    )

    with caplog.at_level(logging.WARNING):
        await run(world, model).ainvoke(said("שלום"), check_config(PERSON, CHECK))

    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "price, slight" in record.getMessage()
    assert CHECK in record.getMessage()


async def test_a_hebrew_reply_with_numbers_and_shekels_stands(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("פריים + 1.5% ל-30 חודשים: 1,322 ₪")])
    graph = run(world, model)

    await graph.ainvoke(said("שלום"), check_config(PERSON, CHECK))

    assert len(model.received) == 1


async def test_ask_term_ends_the_turn(world: World) -> None:
    await world.checks.set_loan(CHECK, LoanRequest(None, Decimal(80000)))
    model = ScriptedChatModel(replies=[calls(("ask_term", {})), AIMessage("never reached")])
    graph = run(world, model)

    state = await graph.ainvoke(said("אני צריך הלוואה של 80,000"), check_config(PERSON, CHECK))

    assert len(model.received) == 1
    assert state["messages"][-1].content == ASKED_RESULT
    assert [e.data for e in world.sink.events] == [
        {
            "question": {
                "kind": "term",
                "term_months": 24,
                "first_payment": "1750.00",
                "basis": {"kind": "first_payment_target", "amount": "1000", "fits": False},
            },
            "lead_in": None,
        }
    ]


async def test_ask_term_and_ask_in_one_message_are_both_refused(world: World) -> None:
    await world.checks.set_loan(CHECK, LoanRequest(None, Decimal(80000)))
    model = ScriptedChatModel(
        replies=[
            calls(("ask_term", {}), ("ask", {"question": {"field": "purpose"}})),
            AIMessage("אשאל אחת"),
        ]
    )
    graph = run(world, model)

    state = await graph.ainvoke(said("80,000"), check_config(PERSON, CHECK))

    assert all(r.status == "error" for r in tool_messages(state["messages"]))
    assert not world.sink.events
    assert len(model.received) == 2


def test_the_prompt_saves_the_three_examples_in_one_call_one_of_them_a_pension_funds() -> None:
    """The model cannot save part of the examples: the prompt names only the call that saves
    all three, never one that saves a single example or lists the tracks to save."""
    for single in ("save_option", "suggest_tracks", "שתי הדוגמאות"):
        assert single not in SYSTEM_PROMPT, single
    assert SYSTEM_PROMPT.count("save_examples") >= 4
    assert "קרן פנסיה" in SYSTEM_PROMPT


def test_the_prompt_gives_one_form_for_a_tracks_price_and_places_the_ceiling_on_its_line() -> None:
    """The price is the interest ahead of the total it adds up to, in every example the prompt
    gives; a track whose payment never changes has no historical line, so its distance from
    the ceiling ends its line of today's payment."""
    flat = " ".join(SYSTEM_PROMPT.split())
    assert "₪ על 45,000 ₪" not in flat
    assert '"ריבית של כ-13,368 ₪; סכום כולל להחזר: 58,368 ₪ (45,000 + 13,368)"' in flat
    assert '"החזר היום: 969 ₪, 19% מתחת לתקרה שלך של 1,200 ₪"' in flat
    assert "אל תכתוב שההחזר לא השתנה" in flat


def test_the_prompt_limits_offers_to_what_a_tool_does() -> None:
    """The model offers and reports only actions one of its tools performs. The prompt names
    what a person may ask for and no tool does (approaching a lender, a file, an email, a
    month-by-month schedule), and it forbids asking for contact details."""
    flat = " ".join(SYSTEM_PROMPT.split())
    assert "אין כלי שעושה את זה: אל תציע" in flat
    assert "רק על מה שכלי עשה בתור הזה" in flat
    for missing in ("פנייה לגוף מלווה", "קובץ", "לוח תשלומים חודשי", "כתובת מייל"):
        assert missing in flat, missing


def test_the_prompt_gives_a_yes_or_no_question_its_choices() -> None:
    """A free question without choices is drawn as a text box, so a question answered by yes
    or no, or by one of a few answers, carries them as choices the person taps."""
    flat = " ".join(SYSTEM_PROMPT.split())
    assert "choices של 'כן' ו-'לא'" in flat
    assert "בלי choices המסך מציג תיבת טקסט" in flat
    assert "yes or no" in AskQuestion.model_fields["choices"].description


def test_the_prompt_words_the_historical_payment_as_what_would_have_happened() -> None:
    """The worst period is a scenario, what the payment would have reached had the loan run
    through it, never something that happened to the person."""
    flat = " ".join(SYSTEM_PROMPT.split())
    for happened in ("ההחזר הגיע", "הפריים הגיע", "ההחזר עלה"):
        assert happened not in flat, happened
    assert "ההחזר היה מגיע עד 1,125 ₪" in flat
    assert 'לעולם לא "הגיע"' in flat


def test_the_prompt_calls_the_second_track_an_alternative_and_nothing_more() -> None:
    """The reply names the second track as the card does, "חלופה": an adjective such as
    "suitable" says nothing the person can check, so the prompt neither uses nor allows one."""
    flat = " ".join(SYSTEM_PROMPT.split())
    assert "הכי מתאימה" not in flat
    assert 'בכותרת "חלופה:" בלבד' in flat


def test_the_prompt_no_longer_names_removed_tools() -> None:
    for removed in ("update_profile", "set_goal", "size_loan", "assess_affordability"):
        assert removed not in SYSTEM_PROMPT


def test_the_prompt_asks_to_reuse_the_previous_finances_in_the_designs_words() -> None:
    question = "האם להשתמש בהכנסה החודשית ובהוצאות הקבועות מהבדיקה הקודמת (X₪, Y₪)?"
    assert question in SYSTEM_PROMPT
    assert "(12,000₪, 6,000₪)" in SYSTEM_PROMPT


async def test_a_smaller_loan_is_asked_as_a_free_question_once_the_loan_is_saved(
    world: World,
) -> None:
    await world.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(60000)))
    model = ScriptedChatModel(
        replies=[
            calls(("ask", {"question": {"field": "amount"}})),
            calls(("ask", {"question": {"text": "כמה ללוות?"}})),
            AIMessage("never reached"),
        ]
    )
    graph = run(world, model)

    state = await graph.ainvoke(said("סכום אחר"), check_config(PERSON, CHECK))

    refused, asked = tool_messages(state["messages"])
    assert refused.status == "error" and "already known" in str(refused.content)
    assert asked.content == ASKED_RESULT
    assert "שאלה חופשית עם text" in SYSTEM_PROMPT


async def car_loan_of_60_months(world: World) -> None:
    await world.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(45000)))
    await world.checks.set_term(CHECK, 60)


AVIS_OFFER = {
    "lender": "אוויס",
    "amount": "45000",
    "term_months": 60,
    "monthly_payment": "969",
}
LEUMI_OFFER = {
    "lender": "לאומי",
    "amount": "45000",
    "term_months": 60,
    "stated_rate": "6",
    "monthly_payment": "972",
    "type_words": ["prime"],
}


def recommend(option_id: str) -> tuple[str, dict[str, Any]]:
    return ("present_recommendation", {"preferred_option_id": option_id, "reasoning": "הזולה"})


def test_a_reply_with_no_tool_results_goes_back_to_the_model() -> None:
    assert _after_tools({"messages": [HumanMessage("שלום"), AIMessage("")]}) == "model"


async def test_an_offer_carded_on_the_screen_ends_the_turn(world: World) -> None:
    await car_loan_of_60_months(world)
    model = ScriptedChatModel(replies=[calls(("read_offer", AVIS_OFFER)), AIMessage("never")])

    state = await run(world, model).ainvoke(said("אוויס: 969 ₪ בחודש"), check_config(PERSON, CHECK))

    assert len(model.received) == 1
    assert state["messages"][-1].content == READING_ON_SCREEN
    assert [event.type for event in world.sink.events] == [OFFER_AWAITING]


async def test_an_identified_offer_goes_back_to_the_model_for_the_recommendation(
    world: World,
) -> None:
    await car_loan_of_60_months(world)
    world.engine.readings = LEUMI_READINGS
    world.engine.simulations = [PRIME_SIMULATION]
    model = ScriptedChatModel(
        replies=[
            calls(("read_offer", LEUMI_OFFER)),
            calls(recommend("option-1")),
            AIMessage(f"**{RECOMMENDATION_HEADING}**\nלקחת את ההצעה של לאומי"),
        ]
    )

    await run(world, model).ainvoke(said("לאומי: פריים 6, 972 ₪"), check_config(PERSON, CHECK))

    assert len(model.received) == 3
    assert OFFER_IDENTIFIED in [event.type for event in world.sink.events]
    recommendation = await world.recommendations.latest(CHECK)
    assert recommendation is not None
    assert recommendation.preferred_option_id == "option-1"


async def test_a_carded_offer_beside_an_identified_one_does_not_end_the_turn(world: World) -> None:
    await car_loan_of_60_months(world)
    # Avis states a payment and no number, so its card shows all four readings; only prime
    # plus 6 fits Leumi's 972.
    world.engine.readings = LEUMI_READINGS
    world.engine.simulations = [PRIME_SIMULATION]
    model = ScriptedChatModel(
        replies=[
            calls(("read_offer", AVIS_OFFER), ("read_offer", LEUMI_OFFER)),
            calls(recommend("option-1")),
            AIMessage("ההמלצה מוכנה"),
        ]
    )

    await run(world, model).ainvoke(said("אוויס ולאומי"), check_config(PERSON, CHECK))

    assert len(model.received) == 3
    types = [event.type for event in world.sink.events]
    assert OFFER_AWAITING in types and OFFER_IDENTIFIED in types


async def test_the_lenders_answer_on_the_amount_in_words_saves_the_short_offer(
    world: World,
) -> None:
    await world.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(80000)))
    await world.checks.set_term(CHECK, 60)
    await world.deps.awaiting.save(awaiting_offer(CHECK, "awaiting-1", "אוויס", None))
    world.engine.simulations = [PRIME_SIMULATION]
    model = ScriptedChatModel(
        replies=[
            calls(("answer_offer_amount", {"awaiting_id": "awaiting-1", "covers": True})),
            calls(recommend("option-1")),
            AIMessage("ההמלצה מוכנה"),
        ]
    )

    await run(world, model).ainvoke(
        said("אוויס אמרו שהם נותנים 80,000 באותם תנאים"), check_config(PERSON, CHECK)
    )

    (option,) = await world.options.list(CHECK)
    assert option.lender == "אוויס"
    types = [event.type for event in world.sink.events]
    assert OFFER_SETTLED in types
    assert await world.recommendations.latest(CHECK) is not None


async def test_the_lender_refusing_the_amount_in_words_drops_the_short_offer(
    world: World,
) -> None:
    await world.checks.set_loan(CHECK, LoanRequest("רכב", Decimal(80000)))
    await world.deps.awaiting.save(awaiting_offer(CHECK, "awaiting-1", "אוויס", None))
    model = ScriptedChatModel(
        replies=[
            calls(("answer_offer_amount", {"awaiting_id": "awaiting-1", "covers": False})),
            AIMessage("אפשר להביא הצעה מגוף אחר"),
        ]
    )

    await run(world, model).ainvoke(said("אוויס לא נותנים יותר"), check_config(PERSON, CHECK))

    assert [event.type for event in world.sink.events] == [OFFER_DROPPED]
    assert await world.deps.awaiting.list(CHECK) == []
    assert len(model.received) == 2


async def test_a_refused_read_offer_goes_back_to_the_model(world: World) -> None:
    await car_loan_of_60_months(world)
    nameless = {key: value for key, value in AVIS_OFFER.items() if key != "lender"}
    model = ScriptedChatModel(
        replies=[calls(("read_offer", nameless)), AIMessage("מי נתן את ההצעה?")]
    )

    state = await run(world, model).ainvoke(said("969 ₪ בחודש"), check_config(PERSON, CHECK))

    (refusal,) = tool_messages(state["messages"])
    assert refusal.status == "error"
    assert "lender is missing" in str(refusal.content)
    assert len(model.received) == 2


async def test_read_offer_schema_takes_only_the_three_type_words(world: World) -> None:
    await car_loan_of_60_months(world)
    model = ScriptedChatModel(
        replies=[
            calls(("read_offer", {**AVIS_OFFER, "type_words": ["variable"]})),
            AIMessage("אתקן"),
        ]
    )

    state = await run(world, model).ainvoke(said("אוויס"), check_config(PERSON, CHECK))

    (refusal,) = tool_messages(state["messages"])
    assert refusal.status == "error"
    assert world.engine.calls == []
    (tool,) = [tool for tool in model.tools if tool.name == "read_offer"]
    schema = tool.tool_call_schema.model_json_schema()
    assert schema["properties"]["type_words"]["items"]["enum"] == ["prime", "fixed", "linked"]


HAREL_TRACKS = [
    {"rate_kind": "prime", "rate": "0.5", "cpi_linked": False},
    {"rate_kind": "fixed", "rate": "3.5", "cpi_linked": True},
]


async def test_harels_offer_in_words_without_a_term_opens_the_form_filled_in(
    world: World,
) -> None:
    await car_loan_of_60_months(world)
    model = ScriptedChatModel(
        replies=[
            calls(("ask_offer", {"lender": "הראל פנסיה", "tracks": HAREL_TRACKS})),
            AIMessage("never reached"),
        ]
    )

    state = await run(world, model).ainvoke(
        said("קיבלתי הצעה מהראל פנסיה: פריים פלוס חצי, או קבועה 3.5% צמודה"),
        check_config(PERSON, CHECK),
    )

    assert len(model.received) == 1
    assert state["messages"][-1].content == ASKED_RESULT
    (asked,) = world.sink.events
    assert (asked.type, asked.data["question"]) == (
        QUESTION_ASKED,
        {
            "kind": "offer",
            "lender": "הראל פנסיה",
            "tracks": HAREL_TRACKS,
            "max_term_months": None,
        },
    )


async def test_harels_offer_from_the_form_is_saved_directly(world: World) -> None:
    await car_loan_of_60_months(world)
    world.engine.simulations = [PRIME_SIMULATION, BALLOON_SIMULATION]
    of_the_check = {"principal": "45000", "term_months": 60, "method": "spitzer"}
    tracks = [
        {**of_the_check, "rate_kind": "prime", "prime_spread": "0.5", "cpi_linked": False},
        {**of_the_check, "rate_kind": "fixed", "annual_rate": "3.5", "cpi_linked": True},
    ]
    model = ScriptedChatModel(
        replies=[
            calls(
                (
                    "save_offer",
                    {"tracks": tracks, "lender": "הראל פנסיה", "max_term_months": 84},
                )
            ),
            calls(recommend("option-1")),
            AIMessage("ההמלצה מוכנה"),
        ]
    )
    form_line = (
        "קיבלתי הצעה מגוף מלווה, הראל פנסיה: (1) פריים פלוס 0.5%, לא צמוד למדד (2) ריבית קבועה "
        "3.5%, צמוד למדד. לתקופה של עד 84 חודשים, בתשלומים חודשיים שווים."
    )

    await run(world, model).ainvoke(said(form_line), check_config(PERSON, CHECK))

    saved = await world.options.list(CHECK)
    assert [(option.source, option.lender) for option in saved] == [("offer", "הראל פנסיה")] * 2
    assert [event.type for event in world.sink.events if event.type == QUESTION_ASKED] == []
    assert not [event for event in world.sink.events if event.type.startswith("offer.")]
