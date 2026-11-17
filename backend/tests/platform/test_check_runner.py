"""The runner runs one turn per check at a time within the person's message cap, streams the
reply's text live, stores the complete reply, and reports a failed turn without losing the check.
It answers the opening card, a confirmed term with no option and a skipped offer form without
calling the model, and saves a confirmed reading or an amount answer before any message."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
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
    InMemoryAwaitingOfferRepository,
    InMemoryCheckEventStore,
    InMemoryCheckRepository,
    InMemoryOptionRepository,
    InMemoryRecommendationRepository,
    ScriptedChatModel,
    awaiting_offer,
    readings_of,
)
from loan_agent.adapters.memory_bus import InMemoryEventBus
from loan_agent.application.agent_graph import (
    SAME_CALLS_LIMIT,
    TURN_STEP_LIMIT,
    build_agent_graph,
)
from loan_agent.application.check_tools import ToolDeps, ToolError
from loan_agent.application.event_sink import CheckEventSink, check_channel
from loan_agent.domain.errors import (
    CheckArchivedError,
    CheckNotFoundError,
    CheckNotRestorableError,
    TurnConflictError,
    TurnLimitError,
)
from loan_agent.domain.models import Check, Finances, LoanRequest, Option, Recommendation, User
from loan_agent.platform.check_runner import (
    DESCRIBE_THE_OFFER,
    FAILURE_MESSAGE,
    OFFER_FORM_SHOWN,
    OPENING_CARD_ANSWERED,
    TERM_CARD_FOR_CEILING,
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
LOAN = LoanRequest("רכב", Decimal(55000))
FINANCES = Finances(Decimal(8000), Decimal(6000))


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
    awaiting = InMemoryAwaitingOfferRepository()
    recommendations = InMemoryRecommendationRepository()
    checks.option_store, checks.awaiting_store = options, awaiting
    checks.recommendation_store = recommendations
    deps = ToolDeps(
        checks=checks,
        options=options,
        awaiting=awaiting,
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
        world.store,
        world.deps.sink,
        world.deps,
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


def calls_size_loan(text: str = "", call_id: str = "call-size", goal_price: str = "1") -> AIMessage:
    call = {"name": "size_loan", "args": {"goal_price": goal_price}, "id": call_id}
    return AIMessage(content=text, tool_calls=[{**call, "type": "tool_call"}])


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

    assert check == Check(check.id, PERSON.id, NOW, None, None, None, None, Finances())
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


async def test_a_draft_with_english_words_is_retracted_from_the_page(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage("ההפרש slight בסך הכול"), AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)

    async with world.bus.subscribe(check_channel(check.id)) as queue:
        await checks.send(PERSON, check.id, "שלום")
        await checks.drain()
        live = published(queue)

    (retracted,) = [event["data"] for event in live if event["type"] == "message.retracted"]
    deltas = [event["data"] for event in live if event["type"] == "message.delta"]
    drafts = [delta["text"] for delta in deltas if delta["message_id"] == retracted["message_id"]]
    assert all("slight" not in text for text in drafts)
    assistant = [event["data"]["text"] for event in live if event["type"] == "message.assistant"]
    assert assistant == [REPLY]


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


async def test_model_that_repeats_the_same_call_fails_the_turn_at_the_third(world: World) -> None:
    ran = 0

    async def sized() -> str:
        nonlocal ran
        ran += 1
        return "loan_amount: 80000"

    repeated = [calls_size_loan(call_id=f"call-{index}") for index in range(6)]
    model = ScriptedChatModel(replies=repeated)
    checks = runner(world, model, [engine_tool(sized)])
    check = await checks.create(PERSON)

    await checks.send(PERSON, check.id, "כמה ללוות?")
    await checks.drain()

    assert (len(model.received), ran) == (SAME_CALLS_LIMIT + 1, SAME_CALLS_LIMIT)
    assert (await stored(world, check.id))[-2:] == [
        ("turn.failed", {"message": FAILURE_MESSAGE}),
        ("turn.status", {"status": "idle"}),
    ]


async def test_model_that_never_stops_calling_tools_fails_the_turn_at_the_step_limit(
    world: World,
) -> None:
    async def sized() -> str:
        return "loan_amount: 80000"

    endless = [
        calls_size_loan(call_id=f"call-{index}", goal_price=str(index))
        for index in range(TURN_STEP_LIMIT)
    ]
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

    save = {"tracks": [PRIME_TRACK], "lender": "Bank", "offer_date": "2026-10-20"}
    parallel = AIMessage(
        content="",
        tool_calls=[
            {"name": "save_offer", "args": save, "id": "call-save", "type": "tool_call"},
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
    await world.checks.set_loan(check.id, LoanRequest(None, Decimal(80000)))
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
    # The turn stored an event after it started, as a saved loan mid-turn does.
    await world.store.append(interrupted.id, "loan.set", {})
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


async def recommended_check(world: World, checks: CheckRunner) -> Check:
    """A check with a loan, a term, a derived ceiling, finances and one saved option."""
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LOAN)
    await world.checks.set_term(check.id, 48)
    await world.checks.set_finances(check.id, FINANCES)
    await world.checks.set_ceiling(check.id, Decimal("4700.00"), "finances")
    await world.options.add(
        Option(
            "option-1",
            check.id,
            {"tracks": [PRIME_TRACK]},
            "offer",
            None,
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
    assert (clone.loan, clone.term_months, clone.payment_ceiling, clone.ceiling_source) == (
        LOAN,
        48,
        Decimal("4700.00"),
        "finances",
    )
    assert (clone.finances, clone.archived_at) == (FINANCES, None)
    assert clone.created_at == NOW + timedelta(minutes=1)
    assert [o.id for o in await world.options.list(clone.id)] == ["option-1"]
    assert await stored(world, source.id) == [
        *await stored(world, clone.id),
        ("check.cloned", {"clone_id": clone.id}),
    ]
    await checks.send(PERSON, clone.id, "ממשיכים")
    await checks.drain()
    texts = [m.text for m in model.received[1] if isinstance(m, HumanMessage | AIMessage)]
    assert texts == ["שלום", REPLY, "ממשיכים"]


async def test_a_clone_of_a_clones_source_does_not_copy_the_earlier_handoff(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    source = await recommended_check(world, checks)
    await checks.clone(PERSON, source.id)

    second = await checks.clone(PERSON, source.id)

    assert "check.cloned" not in [type for type, _ in await stored(world, second.id)]


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


async def test_the_person_archives_a_check_and_restores_it(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[AIMessage(REPLY)]))
    check = await recommended_check(world, checks)
    world.clock.value = NOW + timedelta(minutes=1)

    await checks.archive(PERSON, check.id)

    assert (await world.checks.get(PERSON.id, check.id)).archived_at == world.clock.value
    assert await stored(world, check.id) == [
        (
            "check.archived",
            {"archived_at": world.clock.value.isoformat()},
        )
    ]
    with pytest.raises(CheckArchivedError):
        await checks.archive(PERSON, check.id)

    await checks.restore(PERSON, check.id)

    assert (await world.checks.get(PERSON.id, check.id)).archived_at is None
    assert (await stored(world, check.id))[-1] == ("check.restored", {})
    await checks.send(PERSON, check.id, "שלום")
    await checks.drain()


async def test_a_check_that_is_not_archived_is_not_restored(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    open_check = await checks.create(PERSON)

    with pytest.raises(CheckNotRestorableError):
        await checks.restore(PERSON, open_check.id)


async def test_save_finances_stores_the_figures_and_the_derived_ceiling(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await checks.create(PERSON)

    saved = await checks.save_finances(PERSON, check.id, {"net_fixed_income": "8000"})
    assert (saved.finances, saved.payment_ceiling) == (Finances(Decimal(8000), None), None)
    saved = await checks.save_finances(PERSON, check.id, {"fixed_expenses": "6000"})

    assert (saved.finances, saved.payment_ceiling, saved.ceiling_source) == (
        FINANCES,
        Decimal("4700.00"),
        "finances",
    )
    assert [type for type, _ in await stored(world, check.id)] == [
        "finances.updated",
        "finances.updated",
    ]


async def test_saves_from_the_page_are_refused_for_an_archived_or_busy_check(world: World) -> None:
    started = asyncio.Event()

    async def hangs() -> str:
        started.set()
        await asyncio.Event().wait()
        return "never"

    checks = runner(world, ScriptedChatModel(replies=[calls_size_loan()]), [engine_tool(hangs)])
    archived = await checks.create(PERSON)
    await world.checks.archive(archived.id, NOW)
    busy = await checks.create(PERSON)
    await checks.send(PERSON, busy.id, "כמה ללוות?")
    await started.wait()

    with pytest.raises(CheckArchivedError):
        await checks.save_finances(PERSON, archived.id, {"fixed_expenses": "1"})
    with pytest.raises(TurnConflictError):
        await checks.save_finances(PERSON, busy.id, {"fixed_expenses": "1"})
    with pytest.raises(CheckNotFoundError):
        await checks.save_finances(OTHER_PERSON, busy.id, {"fixed_expenses": "1"})
    with pytest.raises(CheckArchivedError):
        await checks.save_term(PERSON, archived.id, 60, None)
    with pytest.raises(TurnConflictError):
        await checks.save_term(PERSON, busy.id, 60, None)
    await checks.aclose()


async def test_confirming_a_reading_saves_the_offer_before_any_message(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LOAN)
    await world.checks.set_term(check.id, 60)
    await world.deps.awaiting.save(
        awaiting_offer(check.id, "awaiting-1", "אוויס", None, LOAN.amount)
    )
    world.engine.simulations = [PRIME_SIMULATION]

    await checks.confirm_reading(PERSON, check.id, "awaiting-1", "fixed_unlinked")
    await checks.drain()

    types = [type for type, _ in await stored(world, check.id)]
    assert types[-2:] == ["option.saved", "offer.settled"]
    assert "message.user" not in types
    assert model.received == []
    assert await world.deps.awaiting.list(check.id) == []


async def test_a_reading_is_not_confirmed_on_a_busy_or_archived_check(world: World) -> None:
    started = asyncio.Event()

    async def hangs() -> str:
        started.set()
        await asyncio.Event().wait()
        return "never"

    checks = runner(world, ScriptedChatModel(replies=[calls_size_loan()]), [engine_tool(hangs)])
    archived = await checks.create(PERSON)
    await world.checks.archive(archived.id, NOW)
    busy = await checks.create(PERSON)
    await checks.send(PERSON, busy.id, "כמה ללוות?")
    await started.wait()

    with pytest.raises(CheckArchivedError):
        await checks.confirm_reading(PERSON, archived.id, "awaiting-1", "fixed_unlinked")
    with pytest.raises(TurnConflictError):
        await checks.confirm_reading(PERSON, busy.id, "awaiting-1", "fixed_unlinked")
    with pytest.raises(CheckArchivedError):
        await checks.answer_amount(PERSON, archived.id, "awaiting-1", False, None)
    with pytest.raises(TurnConflictError):
        await checks.answer_amount(PERSON, busy.id, "awaiting-1", False, None)
    await checks.aclose()


async def test_answering_the_amount_question_saves_or_drops_before_any_message(
    world: World,
) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LOAN)
    await world.checks.set_term(check.id, 60)
    for awaiting_id in ("awaiting-1", "awaiting-2"):
        await world.deps.awaiting.save(awaiting_offer(check.id, awaiting_id, "אוויס", None))
    world.engine.simulations = [PRIME_SIMULATION]

    await checks.answer_amount(PERSON, check.id, "awaiting-1", True, "fixed_unlinked")
    await checks.answer_amount(PERSON, check.id, "awaiting-2", False, None)
    await checks.drain()

    types = [type for type, _ in await stored(world, check.id)]
    assert types[-3:] == ["option.saved", "offer.settled", "offer.dropped"]
    assert "message.user" not in types
    assert model.received == []
    assert await world.deps.awaiting.list(check.id) == []


MARKET_SAMPLE = "מהי ריבית הפריים הנוכחית"


async def test_the_market_sample_is_answered_from_the_data_with_no_model_call(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)

    await checks.send_market_sample(PERSON, check.id, MARKET_SAMPLE)
    await checks.drain()

    events = await stored(world, check.id)
    assert [type for type, _ in events] == [
        "message.user",
        "turn.status",
        "message.assistant",
        "chart.shown",
        "chart.shown",
        "turn.status",
    ]
    assert events[2][1]["text"].startswith("ריבית הפריים נכון ל-")
    assert [data["series"] for type, data in events if type == "chart.shown"] == ["prime", "cpi"]
    assert world.engine.calls == [("market_series", {"months": 60})]
    assert model.received == []


OFFER_SAMPLE = "קיבלתי הצעה להלוואה מגוף מלווה"


async def test_offer_sample_shows_the_form_without_a_model_call(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LoanRequest("רכב", Decimal(60000)))

    await checks.send_offer_sample(PERSON, check.id, OFFER_SAMPLE)
    await checks.drain()

    events = await stored(world, check.id)
    assert [type for type, _ in events] == [
        "message.user",
        "turn.status",
        "question.asked",
        "turn.status",
    ]
    assert events[2][1] == {
        "question": {"kind": "offer", "lender": None, "tracks": [], "max_term_months": None},
        "lead_in": None,
    }
    assert model.received == []


async def test_the_next_turn_reads_that_the_offer_form_was_shown(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LoanRequest("רכב", Decimal(60000)))
    await checks.send_offer_sample(PERSON, check.id, OFFER_SAMPLE)
    await checks.drain()

    await checks.send(PERSON, check.id, "קיבלתי הצעה מגוף מלווה, הבנק: (1) פריים + 1%")
    await checks.drain()

    said = [message for message in model.received[0] if not isinstance(message, SystemMessage)]
    assert [type(message) for message in said] == [HumanMessage, AIMessage, HumanMessage]
    assert (said[0].content, said[1].content) == (OFFER_SAMPLE, OFFER_FORM_SHOWN)


async def test_an_offer_sample_on_a_check_with_no_loan_reports_a_failed_turn(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await checks.create(PERSON)

    await checks.send_offer_sample(PERSON, check.id, OFFER_SAMPLE)
    await checks.drain()

    types = [type for type, _ in await stored(world, check.id)]
    assert types == ["message.user", "turn.status", "turn.failed", "turn.status"]


async def test_the_next_turn_reads_the_market_answer(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await checks.send_market_sample(PERSON, check.id, MARKET_SAMPLE)
    await checks.drain()

    await checks.send(PERSON, check.id, "ומה היה ב-2022?")
    await checks.drain()

    said = [message for message in model.received[0] if not isinstance(message, SystemMessage)]
    assert [type(message) for message in said] == [HumanMessage, AIMessage, HumanMessage]
    assert said[0].content == MARKET_SAMPLE
    assert str(said[1].content).startswith("ריבית הפריים נכון ל-")


async def test_the_market_sample_counts_as_a_message_and_keeps_the_send_guards(
    world: World,
) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await checks.create(PERSON)
    for _ in range(TURN_LIMIT):
        await checks.send_market_sample(PERSON, check.id, MARKET_SAMPLE)
        await checks.drain()

    with pytest.raises(TurnLimitError):
        await checks.send_market_sample(PERSON, check.id, MARKET_SAMPLE)
    await world.checks.archive(check.id, NOW)
    with pytest.raises(CheckArchivedError):
        await checks.send_market_sample(PERSON, check.id, MARKET_SAMPLE)


async def test_an_engine_failure_fails_the_market_answer(world: World) -> None:
    world.engine.market_error = EngineError("engine unreachable")
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await checks.create(PERSON)

    await checks.send_market_sample(PERSON, check.id, MARKET_SAMPLE)
    await checks.drain()

    assert (await stored(world, check.id))[-2:] == [
        ("turn.failed", {"message": FAILURE_MESSAGE}),
        ("turn.status", {"status": "idle"}),
    ]


CEILING_QUESTION_DATA = {
    "question": {
        "field": "payment_ceiling",
        "offer_clone": False,
        "text": None,
        "choices": None,
    },
    "lead_in": None,
}


async def unchecked_check(world: World, checks: CheckRunner) -> Check:
    """A check with a loan and a recommendation made without a ceiling."""
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LOAN)
    await world.deps.recommendations.save(
        Recommendation(check.id, "option-1", None, "זול יותר", LOAN.amount, None, NOW)
    )
    return check


async def test_a_turn_leaving_a_recommendation_without_a_ceiling_ends_with_its_question(
    world: World,
) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY), AIMessage(REPLY)])
    checks = runner(world, model)
    check = await unchecked_check(world, checks)

    await checks.send(PERSON, check.id, "שלום")
    await checks.drain()

    events = await stored(world, check.id)
    assert events[-2:] == [
        ("question.asked", CEILING_QUESTION_DATA),
        ("turn.status", {"status": "idle"}),
    ]
    await checks.send(PERSON, check.id, "2,000")
    await checks.drain()
    said = [m for m in model.received[1] if isinstance(m, AIMessage)]
    assert "payment_ceiling" in str(said[-1].content)
    asked = [e for e in await stored(world, check.id) if e[0] == "question.asked"]
    assert len(asked) == 1


async def test_no_ceiling_question_with_a_ceiling_or_without_a_recommendation(
    world: World,
) -> None:
    checks = runner(world, ScriptedChatModel(replies=[AIMessage(REPLY), AIMessage(REPLY)]))
    with_ceiling = await unchecked_check(world, checks)
    await world.checks.set_ceiling(with_ceiling.id, Decimal(2000), "stated")
    unrecommended = await checks.create(PERSON)

    for check in (with_ceiling, unrecommended):
        await checks.send(PERSON, check.id, "שלום")
        await checks.drain()
        assert "question.asked" not in [type for type, _ in await stored(world, check.id)]


def read_avis_offer() -> AIMessage:
    """The model's call reading Avis's 969 a month, which has no number and no type."""
    args = {"lender": "אוויס", "amount": "45000", "term_months": 60, "monthly_payment": "969"}
    return AIMessage(
        content="",
        tool_calls=[{"name": "read_offer", "args": args, "id": "call-read", "type": "tool_call"}],
    )


@pytest.mark.parametrize("unrecognized", [False, True])
async def test_a_turn_ending_on_an_offers_reading_asks_no_ceiling(
    world: World, unrecognized: bool
) -> None:
    if unrecognized:
        world.engine.readings = readings_of(payment_rate="10.58")
    checks = runner(world, ScriptedChatModel(replies=[read_avis_offer(), AIMessage("never")]))
    check = await unchecked_check(world, checks)

    await checks.send(PERSON, check.id, "אוויס: 45,000 ₪ ל-60 חודשים, 969 ₪ בחודש")
    await checks.drain()

    types = [type for type, _ in await stored(world, check.id)]
    reading = "offer.unrecognized" if unrecognized else "offer.awaiting"
    assert types[-2:] == [reading, "turn.status"]
    assert "question.asked" not in types


async def test_a_turn_ending_with_the_models_question_is_left_alone(world: World) -> None:
    asks = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "ask",
                "args": {"question": {"field": "net_fixed_income"}, "lead_in": None},
                "id": "call-ask",
                "type": "tool_call",
            }
        ],
    )
    checks = runner(world, ScriptedChatModel(replies=[asks]))
    check = await unchecked_check(world, checks)

    await checks.send(PERSON, check.id, "שלום")
    await checks.drain()

    asked = [data for type, data in await stored(world, check.id) if type == "question.asked"]
    assert [question["question"]["field"] for question in asked] == ["net_fixed_income"]


async def test_a_ceiling_on_the_term_card_is_saved_and_brings_a_card_for_it(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LoanRequest(None, Decimal(60000)))
    world.engine.comfortable_terms = 72
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION]

    await checks.send_term_ceiling(PERSON, check.id, "החזר חודשי מרבי: 1,000 ₪", Decimal(1000))
    await checks.drain()

    saved = await world.checks.get(PERSON.id, check.id)
    assert (saved.payment_ceiling, saved.ceiling_source) == (Decimal(1000), "stated")
    events = await stored(world, check.id)
    assert [type for type, _ in events] == [
        "message.user",
        "turn.status",
        "ceiling.set",
        "question.asked",
        "turn.status",
    ]
    question = events[3][1]["question"]
    assert question["term_months"] == 72
    basis = question["basis"]
    assert (basis["kind"], Decimal(basis["amount"]), basis["fits"]) == ("ceiling", 1000, True)
    assert model.received == []

    await checks.send(PERSON, check.id, "אישור: 72 חודשים")
    await checks.drain()
    said = [m for m in model.received[0] if isinstance(m, HumanMessage | AIMessage)]
    assert [str(m.content) for m in said][-3:-1] == [
        "החזר חודשי מרבי: 1,000 ₪",
        TERM_CARD_FOR_CEILING,
    ]


OPENING = "רכב: הלוואה בסך 45,000 ₪"


async def test_the_opening_card_saves_the_loan_and_shows_the_term_card_with_no_model_call(
    world: World,
) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    world.engine.simulations = [PRIME_SIMULATION, PRIME_SIMULATION]

    await checks.send_opening(PERSON, check.id, OPENING, "רכב", Decimal(45000))
    await checks.drain()

    saved = await world.checks.get(PERSON.id, check.id)
    assert saved.loan == LoanRequest("רכב", Decimal(45000))
    events = await stored(world, check.id)
    assert [type for type, _ in events] == [
        "loan.set",
        "message.user",
        "turn.status",
        "question.asked",
        "turn.status",
    ]
    assert events[0][1] == {"purpose": "רכב", "amount": "45000"}
    assert events[1][1] == {"text": OPENING}
    assert (events[2][1], events[4][1]) == ({"status": "running"}, {"status": "idle"})
    assert events[3][1]["question"]["kind"] == "term"
    assert events[3][1]["question"]["basis"]["kind"] == "first_payment_target"
    assert model.received == []

    await checks.send(PERSON, check.id, "אישור: 60 חודשים")
    await checks.drain()
    said = [message for message in model.received[0] if not isinstance(message, SystemMessage)]
    assert [type(message) for message in said] == [HumanMessage, AIMessage, HumanMessage]
    assert (said[0].content, said[1].content) == (OPENING, OPENING_CARD_ANSWERED)


async def test_a_refused_opening_records_nothing(world: World) -> None:
    world.engine.suggest_error = EngineError("principal below 10000")
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await checks.create(PERSON)

    with pytest.raises(ToolError, match="principal below 10000"):
        await checks.send_opening(PERSON, check.id, OPENING, "רכב", Decimal(500))
    await checks.drain()

    assert (await world.checks.get(PERSON.id, check.id)).loan is None
    assert await stored(world, check.id) == []


async def test_an_opening_on_a_check_that_has_a_loan_is_refused(world: World) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LOAN)

    with pytest.raises(ToolError, match="already"):
        await checks.send_opening(PERSON, check.id, OPENING, "רכב", Decimal(45000))

    assert (await world.checks.get(PERSON.id, check.id)).loan == LOAN
    assert await stored(world, check.id) == []


TERM_CONFIRMED = "אישור: 60 חודשים"


async def test_a_confirmed_term_with_no_option_opens_the_offer_form_with_no_model_call(
    world: World,
) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LOAN)
    await world.checks.set_term(check.id, 60)

    await checks.send_term_confirmation(PERSON, check.id, TERM_CONFIRMED)
    await checks.drain()

    events = await stored(world, check.id)
    assert [type for type, _ in events] == [
        "message.user",
        "turn.status",
        "question.asked",
        "turn.status",
    ]
    question = events[2][1]["question"]
    assert (question["kind"], question["lender"], question["tracks"]) == ("offer", None, [])
    assert model.received == []


async def test_a_confirmed_term_with_examples_only_runs_the_model(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LOAN)
    await world.checks.set_term(check.id, 60)
    await world.options.add(
        Option(
            "example-1",
            check.id,
            {"tracks": [PRIME_TRACK]},
            "example",
            None,
            None,
            None,
            PRIME_SIMULATION.figures,
            NOW,
        )
    )

    await checks.send_term_confirmation(PERSON, check.id, TERM_CONFIRMED)
    await checks.drain()

    assert model.received[0][-1].content == TERM_CONFIRMED
    assert "question.asked" not in [type for type, _ in await stored(world, check.id)]


async def test_a_confirmed_term_with_a_saved_offer_runs_the_model(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await recommended_check(world, checks)

    await checks.send_term_confirmation(PERSON, check.id, TERM_CONFIRMED)
    await checks.drain()

    assert model.received[0][-1].content == TERM_CONFIRMED
    assert ("message.assistant", REPLY) in [
        (type, data.get("text")) for type, data in await stored(world, check.id)
    ]


async def test_a_confirmed_term_with_an_awaiting_offer_runs_the_model(world: World) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LOAN)
    await world.checks.set_term(check.id, 60)
    await world.deps.awaiting.save(awaiting_offer(check.id, "awaiting-1", "אוויס", None))

    await checks.send_term_confirmation(PERSON, check.id, TERM_CONFIRMED)
    await checks.drain()

    assert model.received[0][-1].content == TERM_CONFIRMED
    assert "question.asked" not in [type for type, _ in await stored(world, check.id)]


OFFER_SKIP = "דילוג"


async def test_skipping_the_offer_form_invites_a_description_with_no_model_call(
    world: World,
) -> None:
    model = ScriptedChatModel(replies=[AIMessage(REPLY)])
    checks = runner(world, model)
    check = await checks.create(PERSON)

    await checks.send_offer_skip(PERSON, check.id, OFFER_SKIP)
    await checks.drain()

    events = await stored(world, check.id)
    assert [type for type, _ in events] == [
        "message.user",
        "turn.status",
        "message.assistant",
        "turn.status",
    ]
    assert events[2][1]["text"] == DESCRIBE_THE_OFFER
    assert model.received == []

    await checks.send(PERSON, check.id, "אוויס: 45,000 ₪ ל-60 חודשים, 969 ₪ בחודש")
    await checks.drain()
    said = [message for message in model.received[0] if not isinstance(message, SystemMessage)]
    assert [type(message) for message in said] == [HumanMessage, AIMessage, HumanMessage]
    assert (said[0].content, said[1].content) == (OFFER_SKIP, DESCRIBE_THE_OFFER)


async def test_the_three_replies_count_as_messages_and_keep_the_send_guards(
    world: World,
) -> None:
    checks = runner(world, ScriptedChatModel(replies=[]))
    check = await checks.create(PERSON)
    await world.checks.set_loan(check.id, LOAN)
    await checks.send_offer_skip(PERSON, check.id, OFFER_SKIP)
    await checks.drain()
    await checks.send_term_confirmation(PERSON, check.id, TERM_CONFIRMED)
    await checks.drain()
    fresh = await checks.create(PERSON)

    with pytest.raises(TurnLimitError):
        await checks.send_offer_skip(PERSON, check.id, OFFER_SKIP)
    with pytest.raises(TurnLimitError):
        await checks.send_term_confirmation(PERSON, check.id, TERM_CONFIRMED)
    with pytest.raises(TurnLimitError):
        await checks.send_opening(PERSON, fresh.id, OPENING, "רכב", Decimal(45000))
    assert (await world.checks.get(PERSON.id, fresh.id)).loan is None
    await world.checks.archive(check.id, NOW)
    for send in (checks.send_offer_skip, checks.send_term_confirmation):
        with pytest.raises(CheckArchivedError):
            await send(PERSON, check.id, OFFER_SKIP)
    with pytest.raises(CheckArchivedError):
        await checks.send_opening(PERSON, check.id, OPENING, "רכב", Decimal(45000))
    with pytest.raises(CheckNotFoundError):
        await checks.send_opening(OTHER_PERSON, fresh.id, OPENING, "רכב", Decimal(45000))
