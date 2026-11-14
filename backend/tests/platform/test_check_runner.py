"""The runner runs one turn per check at a time within the person's message cap, streams the
reply's text live, stores the complete reply, and reports a failed turn without losing the check."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any
from unittest.mock import ANY

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from fakes import (
    NOW,
    PRIME_SIMULATION,
    PRIME_TRACK,
    Clock,
    FakeLoanEngine,
    Ids,
    InMemoryCheckEventStore,
    InMemoryCheckRepository,
    InMemoryOptionRepository,
    InMemoryProfileRepository,
    InMemoryRecommendationRepository,
    ScriptedChatModel,
)
from loan_agent.adapters.memory_bus import InMemoryEventBus
from loan_agent.application.agent_graph import TURN_STEP_LIMIT, build_agent_graph
from loan_agent.application.check_tools import ToolDeps
from loan_agent.application.event_sink import CheckEventSink, check_channel
from loan_agent.application.profile_saving import save_profile
from loan_agent.domain.errors import (
    CheckArchivedError,
    CheckNotFoundError,
    CheckNotRestorableError,
    TurnConflictError,
    TurnLimitError,
)
from loan_agent.domain.models import Check, Goal, Option, Profile, User
from loan_agent.platform.check_runner import (
    FAILURE_MESSAGE,
    TOOL_CALL_OUTCOME_UNKNOWN,
    CheckRunner,
)
from loan_agent.platform.checkpointer import checkpoint_serde
from loan_agent.ports.engine import EngineError

PERSON = User("1001", "dana@example.com", "Dana")
OTHER_PERSON = User("2002", "omer@example.com", "Omer")
TURN_LIMIT = 2
WINDOW = timedelta(hours=24)
REPLY = "שלום, נתחיל בהכנסה החודשית שלך"
GOAL = Goal("רכב", Decimal(55000))
COMPLETE_PROFILE = Profile(
    savings=Decimal(35000),
    net_fixed_income=Decimal(8000),
    variable_income=Decimal(0),
    fixed_expenses=Decimal(6000),
    existing_loan_payments=Decimal(0),
)


@dataclass
class World:
    clock: Clock
    checks: InMemoryCheckRepository
    store: InMemoryCheckEventStore
    bus: InMemoryEventBus
    engine: FakeLoanEngine
    options: InMemoryOptionRepository
    deps: ToolDeps


@pytest.fixture
def world() -> World:
    clock = Clock()
    checks = InMemoryCheckRepository()
    store = InMemoryCheckEventStore(checks, clock)
    bus = InMemoryEventBus()
    engine = FakeLoanEngine()
    options = InMemoryOptionRepository()
    recommendations = InMemoryRecommendationRepository()
    checks.option_store, checks.recommendation_store = options, recommendations
    deps = ToolDeps(
        profiles=InMemoryProfileRepository(clock),
        checks=checks,
        options=options,
        recommendations=recommendations,
        engine=engine,
        sink=CheckEventSink(store, bus),
        clock=clock,
        new_id=Ids("option"),
    )
    return World(clock, checks, store, bus, engine, options, deps)


def runner(
    world: World,
    model: ScriptedChatModel,
    engine_tools: list[BaseTool] | None = None,
    turn_limit_overrides: Mapping[str, int] | None = None,
) -> CheckRunner:
    graph = build_agent_graph(
        model,
        engine_tools=[] if engine_tools is None else engine_tools,
        tool_deps=world.deps,
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
    )
    return CheckRunner(
        graph,
        world.checks,
        world.deps.profiles,
        world.store,
        world.deps.sink,
        turn_limit=TURN_LIMIT,
        turn_limit_overrides={} if turn_limit_overrides is None else turn_limit_overrides,
        window=WINDOW,
        clock=world.clock,
    )


def engine_tool(run: Any) -> BaseTool:
    async def size_loan(goal_price: str) -> str:
        result: str = await run()
        return result

    return StructuredTool.from_function(
        coroutine=size_loan, name="size_loan", description="Size the loan"
    )


def calls_size_loan(text: str = "", call_id: str = "call-size") -> AIMessage:
    return AIMessage(
        content=text,
        tool_calls=[
            {"name": "size_loan", "args": {"goal_price": "1"}, "id": call_id, "type": "tool_call"}
        ],
    )


async def stored(world: World, check_id: str) -> list[tuple[str, dict[str, Any]]]:
    return [(event.type, dict(event.data)) for event in await world.store.list(check_id, 0)]


def published(queue: asyncio.Queue[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


async def test_send_emits_user_message_and_runs_turn(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)

    check = await checks.create(PERSON)
    await checks.send(PERSON, check.id, "אני רוצה לקנות רכב")
    await checks.drain()

    assert check == Check(check.id, PERSON.id, NOW, None, None)
    assert await world.checks.get(PERSON.id, check.id) == check
    events = await stored(world, check.id)
    assert [type for type, _ in events] == [
        "message.user",
        "turn.status",
        "message.assistant",
        "turn.status",
    ]
    assert events[0][1] == {"text": "אני רוצה לקנות רכב"}
    assert events[1][1] == {"status": "running"}
    assert events[2][1]["text"] == REPLY
    assert events[3][1] == {"status": "idle"}
    assert model.received[0][-1] == HumanMessage("אני רוצה לקנות רכב", id=model.received[0][-1].id)


async def test_reply_streams_the_text_so_far_then_stores_the_complete_message(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[AIMessage(REPLY)]))
    check = await checks.create(PERSON)

    async with world.bus.subscribe(check_channel(check.id)) as queue:
        await checks.send(PERSON, check.id, "שלום")
        await checks.drain()
        live = published(queue)

    deltas = [event for event in live if event["type"] == "message.delta"]
    (assistant,) = [event for event in live if event["type"] == "message.assistant"]
    assert len(deltas) > 1
    assert all("seq" not in delta for delta in deltas)
    assert {delta["data"]["message_id"] for delta in deltas} == {assistant["data"]["message_id"]}
    texts = [delta["data"]["text"] for delta in deltas]
    assert all(later.startswith(earlier) for earlier, later in pairwise(texts))
    assert texts[-1] == assistant["data"]["text"] == REPLY
    assert live.index(deltas[-1]) < live.index(assistant)
    assert "message.delta" not in [type for type, _ in await stored(world, check.id)]


async def test_tool_call_chunks_are_not_published(world: World) -> None:
    async def sized() -> str:
        return "loan_amount: 80000"

    model = ScriptedChatModel(replies=[calls_size_loan("רגע, אני בודק"), AIMessage(REPLY)])
    checks = runner(world, model, [engine_tool(sized)])
    check = await checks.create(PERSON)

    async with world.bus.subscribe(check_channel(check.id)) as queue:
        await checks.send(PERSON, check.id, "כמה ללוות?")
        await checks.drain()
        live = published(queue)

    deltas = [event["data"] for event in live if event["type"] == "message.delta"]
    assert all(set(delta) == {"message_id", "text"} and delta["text"] for delta in deltas)
    last_text = {delta["message_id"]: delta["text"] for delta in deltas}
    assert list(last_text.values()) == ["רגע, אני בודק", REPLY]
    assistant = [event["data"]["text"] for event in live if event["type"] == "message.assistant"]
    assert assistant == ["רגע, אני בודק", REPLY]


async def test_second_message_while_running_is_conflict(world: World) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked() -> str:
        started.set()
        await release.wait()
        return "loan_amount: 80000"

    model = ScriptedChatModel(replies=[calls_size_loan(), AIMessage(REPLY), AIMessage(REPLY)])
    checks = runner(world, model, [engine_tool(blocked)])
    busy = await checks.create(PERSON)
    other = await checks.create(PERSON)

    await checks.send(PERSON, busy.id, "כמה ללוות?")
    await started.wait()
    with pytest.raises(TurnConflictError):
        await checks.send(PERSON, busy.id, "עוד שאלה")
    await checks.send(PERSON, other.id, "בדיקה נוספת")
    release.set()
    await checks.drain()

    user_messages = [data for type, data in await stored(world, busy.id) if type == "message.user"]
    assert user_messages == [{"text": "כמה ללוות?"}]
    assert [type for type, _ in await stored(world, other.id)] == [
        "message.user",
        "turn.status",
        "message.assistant",
        "turn.status",
    ]


async def test_an_override_sets_one_persons_limit_and_leaves_the_rest_on_the_default(
    world: World,
) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY) for _ in range(5)])
    checks = runner(world, model, turn_limit_overrides={PERSON.email: TURN_LIMIT + 1})
    raised = await checks.create(PERSON)
    default = await checks.create(OTHER_PERSON)

    for _ in range(TURN_LIMIT + 1):
        await checks.send(PERSON, raised.id, "שלום")
        await checks.drain()
    for _ in range(TURN_LIMIT):
        await checks.send(OTHER_PERSON, default.id, "שלום")
        await checks.drain()

    with pytest.raises(TurnLimitError) as refused:
        await checks.send(PERSON, raised.id, "שלום")
    assert refused.value.limit == TURN_LIMIT + 1
    with pytest.raises(TurnLimitError) as refused:
        await checks.send(OTHER_PERSON, default.id, "שלום")
    assert refused.value.limit == TURN_LIMIT


@pytest.mark.parametrize(
    ("email", "sends"), [("Dana@Example.com", TURN_LIMIT + 1), (None, TURN_LIMIT)]
)
async def test_an_override_ignores_the_emails_case_and_a_person_without_one_has_the_default(
    world: World, email: str | None, sends: int
) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY) for _ in range(sends)])
    checks = runner(world, model, turn_limit_overrides={"dana@example.com": TURN_LIMIT + 1})
    person = User(PERSON.id, email, PERSON.name)
    check = await checks.create(person)

    for _ in range(sends):
        await checks.send(person, check.id, "שלום")
        await checks.drain()

    with pytest.raises(TurnLimitError):
        await checks.send(person, check.id, "שלום")


async def test_delete_removes_the_check_and_its_events(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[AIMessage(REPLY)]))
    check = await checks.create(PERSON)
    await checks.send(PERSON, check.id, "שלום")
    await checks.drain()

    await checks.delete(PERSON, check.id)

    with pytest.raises(CheckNotFoundError):
        await world.checks.get(PERSON, check.id)
    assert await stored(world, check.id) == []


async def test_delete_refuses_another_persons_check(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await checks.create(OTHER_PERSON)

    with pytest.raises(CheckNotFoundError):
        await checks.delete(PERSON, check.id)

    assert await world.checks.get(OTHER_PERSON.id, check.id) == check


async def test_delete_gives_back_none_of_the_messages_sent_on_the_check(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY) for _ in range(TURN_LIMIT)])
    checks = runner(world, model)
    deleted = await checks.create(PERSON)
    for _ in range(TURN_LIMIT):
        await checks.send(PERSON, deleted.id, "שלום")
        await checks.drain()
    await checks.delete(PERSON, deleted.id)
    next_check = await checks.create(PERSON)

    with pytest.raises(TurnLimitError) as refused:
        await checks.send(PERSON, next_check.id, "שלום")

    assert refused.value.next_allowed == NOW + WINDOW


async def test_turn_limit_counts_messages_across_checks_and_reports_next_time(
    world: World,
) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY) for _ in range(4)])
    checks = runner(world, model)
    first = await checks.create(PERSON)
    second = await checks.create(PERSON)
    others = await checks.create(OTHER_PERSON)
    await checks.send(OTHER_PERSON, others.id, "שלום")
    await checks.drain()

    await checks.send(PERSON, first.id, "שלום")
    await checks.drain()
    world.clock.value = NOW + timedelta(hours=1)
    await checks.send(PERSON, second.id, "שלום")
    await checks.drain()
    world.clock.value = NOW + timedelta(hours=2)
    with pytest.raises(TurnLimitError) as refused:
        await checks.send(PERSON, first.id, "עוד שאלה")

    assert refused.value.limit == TURN_LIMIT
    assert refused.value.next_allowed == NOW + WINDOW
    assert [type for type, _ in await stored(world, first.id)].count("message.user") == 1

    world.clock.value = refused.value.next_allowed
    await checks.send(PERSON, first.id, "עוד שאלה")
    await checks.drain()

    assert [type for type, _ in await stored(world, first.id)][-3:] == [
        "turn.status",
        "message.assistant",
        "turn.status",
    ]


async def test_engine_failure_mid_turn_emits_turn_failed_and_check_stays_usable(
    world: World,
) -> None:
    async def unreachable() -> str:
        raise EngineError("engine unreachable at http://engine:8100")

    model = ScriptedChatModel(replies=[calls_size_loan(), AIMessage(REPLY)])
    checks = runner(world, model, [engine_tool(unreachable)])
    check = await checks.create(PERSON)

    async with world.bus.subscribe(check_channel(check.id)) as queue:
        await checks.send(PERSON, check.id, "כמה ללוות?")
        await checks.drain()
        live = published(queue)

    assert (await stored(world, check.id))[-2:] == [
        ("turn.failed", {"message": FAILURE_MESSAGE}),
        ("turn.status", {"status": "idle"}),
    ]
    assert not any("unreachable" in str(event) for event in live)

    await checks.send(PERSON, check.id, "ננסה שוב")
    await checks.drain()

    (reply_type, reply), last = (await stored(world, check.id))[-2:]
    assert (reply_type, reply["text"]) == ("message.assistant", REPLY)
    assert last == ("turn.status", {"status": "idle"})


async def test_model_that_never_stops_calling_tools_fails_the_turn_at_the_step_limit(
    world: World,
) -> None:
    async def sized() -> str:
        return "loan_amount: 80000"

    endless = [calls_size_loan(call_id=f"call-{index}") for index in range(TURN_STEP_LIMIT)]
    model = ScriptedChatModel(replies=endless)
    checks = runner(world, model, [engine_tool(sized)])
    check = await checks.create(PERSON)

    await checks.send(PERSON, check.id, "כמה ללוות?")
    await checks.drain()

    assert model.replies, "the turn ended before the model ran out of tool calls"
    assert len(model.received) <= TURN_STEP_LIMIT // 2
    assert (await stored(world, check.id))[-2:] == [
        ("turn.failed", {"message": FAILURE_MESSAGE}),
        ("turn.status", {"status": "idle"}),
    ]


class FailsFirstCall(ScriptedChatModel):
    """Raises on its first call, as an unreachable provider does, then answers its replies."""

    failed: bool = False

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        if not self.failed:
            self.failed = True
            raise ConnectionError("provider unreachable")
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            yield chunk


async def test_turn_after_a_model_failure_sends_both_messages_of_the_person(world: World) -> None:
    model = FailsFirstCall(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await checks.send(PERSON, check.id, "כמה ללוות?")
    await checks.drain()
    assert (await stored(world, check.id))[-2][0] == "turn.failed"

    await checks.send(PERSON, check.id, "ננסה שוב")
    await checks.drain()

    (seen,) = model.received
    assert [type(message) for message in seen[2:]] == [HumanMessage, HumanMessage]
    assert [message.content for message in seen[2:]] == ["כמה ללוות?", "ננסה שוב"]
    (reply_type, reply), last = (await stored(world, check.id))[-2:]
    assert (reply_type, reply["text"]) == ("message.assistant", REPLY)
    assert last == ("turn.status", {"status": "idle"})


async def test_turn_after_failure_answers_the_unfinished_tool_calls(world: World) -> None:
    async def unreachable() -> str:
        raise EngineError("engine unreachable")

    model = ScriptedChatModel(replies=[calls_size_loan(call_id="call-lost"), AIMessage(REPLY)])
    checks = runner(world, model, [engine_tool(unreachable)])
    check = await checks.create(PERSON)
    await checks.send(PERSON, check.id, "כמה ללוות?")
    await checks.drain()

    await checks.send(PERSON, check.id, "ננסה שוב")
    await checks.drain()

    *_, call, answer, retry = model.received[1]
    assert isinstance(call, AIMessage) and call.tool_calls[0]["id"] == "call-lost"
    assert isinstance(answer, ToolMessage) and answer.tool_call_id == "call-lost"
    assert (answer.status, answer.content) == ("error", TOOL_CALL_OUTCOME_UNKNOWN)
    assert retry.content == "ננסה שוב"


async def test_saved_sibling_of_a_failed_call_is_reported_as_possibly_done(world: World) -> None:
    world.engine.simulations.append(PRIME_SIMULATION)
    check_ids: list[str] = []

    async def fails_after_the_save() -> str:
        while not await world.options.list(check_ids[0]):
            await asyncio.sleep(0)
        raise EngineError("engine unreachable")

    save = {
        "loan": {"tracks": [PRIME_TRACK]},
        "source": "offer",
        "lender": "Bank",
        "offer_date": "2026-10-20",
    }
    parallel = AIMessage(
        content="",
        tool_calls=[
            {"name": "save_option", "args": save, "id": "call-save", "type": "tool_call"},
            {
                "name": "size_loan",
                "args": {"goal_price": "1"},
                "id": "call-size",
                "type": "tool_call",
            },
        ],
    )
    model = ScriptedChatModel(replies=[parallel, AIMessage(REPLY)])
    checks = runner(world, model, [engine_tool(fails_after_the_save)])
    check = await checks.create(PERSON)
    check_ids.append(check.id)
    await checks.send(PERSON, check.id, "תשמור את המסלול")
    await checks.drain()

    await checks.send(PERSON, check.id, "ננסה שוב")
    await checks.drain()

    answers = [message for message in model.received[1] if isinstance(message, ToolMessage)]
    assert {(answer.tool_call_id, answer.content) for answer in answers} == {
        ("call-save", TOOL_CALL_OUTCOME_UNKNOWN),
        ("call-size", TOOL_CALL_OUTCOME_UNKNOWN),
    }
    assert len(await world.options.list(check.id)) == 1
    assert [type for type, _ in await stored(world, check.id)].count("option.saved") == 1


async def test_fail_interrupted_ends_turns_a_stopped_process_left_running(world: World) -> None:
    started = asyncio.Event()

    async def hangs() -> str:
        started.set()
        await asyncio.Event().wait()
        return "never"

    stopped = runner(world, ScriptedChatModel(replies=[calls_size_loan()]), [engine_tool(hangs)])
    interrupted = await stopped.create(PERSON)
    finished = await stopped.create(PERSON)
    await world.store.append(finished.id, "turn.status", {"status": "idle"})
    await stopped.send(PERSON, interrupted.id, "כמה ללוות?")
    await started.wait()
    # The turn stored an event after it started, as a profile save mid-turn does.
    await world.store.append(interrupted.id, "profile.updated", {})
    await stopped.aclose()

    restarted = runner(world, ScriptedChatModel(replies=[]))
    await restarted.fail_interrupted()

    assert (await stored(world, interrupted.id))[-2:] == [
        ("turn.failed", {"message": FAILURE_MESSAGE}),
        ("turn.status", {"status": "idle"}),
    ]
    assert await stored(world, finished.id) == [("turn.status", {"status": "idle"})]


async def test_fail_interrupted_leaves_this_processs_running_turns_alone(world: World) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked() -> str:
        started.set()
        await release.wait()
        return "loan_amount: 80000"

    model = ScriptedChatModel(replies=[calls_size_loan(), AIMessage(REPLY)])
    checks = runner(world, model, [engine_tool(blocked)])
    check = await checks.create(PERSON)
    await checks.send(PERSON, check.id, "כמה ללוות?")
    await started.wait()

    await checks.fail_interrupted()
    release.set()
    await checks.drain()

    assert "turn.failed" not in [type for type, _ in await stored(world, check.id)]


async def test_other_persons_check_is_not_found(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    theirs = await checks.create(OTHER_PERSON)

    with pytest.raises(CheckNotFoundError):
        await checks.send(PERSON, theirs.id, "שלום")
    with pytest.raises(CheckNotFoundError):
        await checks.send(PERSON, "no-such-check", "שלום")

    assert await stored(world, theirs.id) == []


async def test_aclose_cancels_running_turns(world: World) -> None:
    started = asyncio.Event()

    async def hangs() -> str:
        started.set()
        await asyncio.Event().wait()
        return "never"

    checks = runner(world, ScriptedChatModel(replies=[calls_size_loan()]), [engine_tool(hangs)])
    check = await checks.create(PERSON)
    await checks.send(PERSON, check.id, "כמה ללוות?")
    await started.wait()

    await checks.aclose()
    await checks.drain()

    assert [type for type, _ in await stored(world, check.id)] == ["message.user", "turn.status"]


def calls_update_profile(**fields: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "update_profile", "args": fields, "id": "call-profile", "type": "tool_call"}
        ],
    )


async def recommended_check(world: World, checks: CheckRunner) -> Check:
    """A check with a goal and one saved option, recommended from the person's profile as saved
    at NOW."""
    profiles = world.deps.profiles
    assert isinstance(profiles, InMemoryProfileRepository)
    profiles.rows[PERSON.id] = (COMPLETE_PROFILE, NOW)
    check = await checks.create(PERSON)
    await world.checks.set_goal(check.id, GOAL)
    await world.checks.snapshot_profile(check.id, NOW)
    await world.options.add(
        Option(
            "option-1",
            check.id,
            {"tracks": [PRIME_TRACK]},
            "offer",
            None,
            None,
            PRIME_SIMULATION.figures,
            NOW,
        )
    )
    return await world.checks.get(PERSON.id, check.id)


async def test_clone_copies_the_check_its_log_and_its_conversation(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY), AIMessage("בבדיקה המשוכפלת")])
    checks = runner(world, model)
    source = await recommended_check(world, checks)
    await checks.send(PERSON, source.id, "שלום")
    await checks.drain()
    world.clock.value = NOW + timedelta(minutes=1)

    clone = await checks.clone(PERSON, source.id)

    assert clone.id != source.id
    assert (clone.goal, clone.profile_snapshot_at, clone.archived_at) == (GOAL, NOW, None)
    assert clone.created_at == NOW + timedelta(minutes=1)
    assert [o.id for o in await world.options.list(clone.id)] == ["option-1"]
    assert await stored(world, clone.id) == await stored(world, source.id)
    await checks.send(PERSON, clone.id, "ממשיכים")
    await checks.drain()
    texts = [m.text for m in model.received[1] if isinstance(m, HumanMessage | AIMessage)]
    assert texts == ["שלום", REPLY, "ממשיכים"]


async def test_a_clones_copied_messages_use_none_of_the_persons_cap(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[AIMessage(REPLY), AIMessage(REPLY)]))
    source = await checks.create(PERSON)
    await checks.send(PERSON, source.id, "שלום")
    await checks.drain()

    clone = await checks.clone(PERSON, source.id)

    await checks.send(PERSON, clone.id, "שלום")
    await checks.drain()


async def test_a_message_to_an_archived_check_is_refused(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await checks.create(PERSON)
    await world.checks.archive(check.id, NOW)

    with pytest.raises(CheckArchivedError):
        await checks.send(PERSON, check.id, "שלום")


async def test_a_profile_change_in_a_recommended_check_continues_in_a_new_check(
    world: World,
) -> None:
    model = ScriptedChatModel(
        replies=[calls_update_profile(savings="23000"), AIMessage("ההמלצה החדשה")]
    )
    checks = runner(world, model)
    archived = await recommended_check(world, checks)
    world.clock.value = NOW + timedelta(minutes=1)

    await checks.send(PERSON, archived.id, "טעיתי, כסף זמין 23,000")
    await checks.drain()

    assert (await world.checks.get(PERSON.id, archived.id)).archived_at == world.clock.value
    events = await stored(world, archived.id)
    assert [type for type, _ in events][-4:] == [
        "check.archived",
        "profile.updated",
        "check.continued",
        "turn.status",
    ]
    continued_id = events[-2][1]["check_id"]
    continued = await world.checks.get(PERSON.id, continued_id)
    assert (continued.goal, continued.profile_snapshot_at, continued.archived_at) == (
        GOAL,
        None,
        None,
    )
    assert await stored(world, continued_id) == [
        (
            "check.follows",
            {
                "check_id": archived.id,
                "changes": [{"field": "savings", "from": "35000", "to": "23000"}],
            },
        ),
        ("goal.set", {"purpose": GOAL.purpose, "price": str(GOAL.price)}),
        ("message.user", {"text": "טעיתי, כסף זמין 23,000"}),
        ("turn.status", {"status": "running"}),
        ("message.assistant", {"message_id": ANY, "text": "ההמלצה החדשה"}),
        ("turn.status", {"status": "idle"}),
    ]
    assert len(model.received) == 2


async def test_the_person_archives_a_check_and_restores_it(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[AIMessage(REPLY)]))
    check = await recommended_check(world, checks)
    world.clock.value = NOW + timedelta(minutes=1)

    await checks.archive(PERSON, check.id)

    assert (await world.checks.get(PERSON.id, check.id)).archived_at == world.clock.value
    assert await stored(world, check.id) == [
        (
            "check.archived",
            {"previous_profile": None, "changes": [], "archived_at": world.clock.value.isoformat()},
        )
    ]
    with pytest.raises(CheckArchivedError):
        await checks.archive(PERSON, check.id)

    await checks.restore(PERSON, check.id)

    assert (await world.checks.get(PERSON.id, check.id)).archived_at is None
    assert (await stored(world, check.id))[-1] == ("check.restored", {})
    await checks.send(PERSON, check.id, "שלום")
    await checks.drain()


async def test_a_check_archived_by_a_profile_change_is_not_restored(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await recommended_check(world, checks)
    world.clock.value = NOW + timedelta(minutes=1)
    await save_profile(
        PERSON.id,
        {"savings": "23000"},
        world.deps.profiles,
        world.checks,
        world.deps.sink,
        world.clock,
    )

    with pytest.raises(CheckNotRestorableError):
        await checks.restore(PERSON, check.id)
    open_check = await checks.create(PERSON)
    with pytest.raises(CheckNotRestorableError):
        await checks.restore(PERSON, open_check.id)
