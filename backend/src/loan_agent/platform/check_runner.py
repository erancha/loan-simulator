"""Runs conversation turns on checks and reports every step of a turn as a check event.

Core building blocks:
- CheckRunner.create: a new, empty check for the signed-in person
- CheckRunner.send: records the person's message and runs the turn as a background task
- CheckRunner.send_term_ceiling: records the payment ceiling the person typed on the term card,
  saves it and shows a term card for it, with no model call
- CheckRunner.send_offer_sample: records the page's offer chip sentence and answers it with the
  offer form, with no model call
- CheckRunner.send_market_sample: records the page's market-data sample and answers it from the
  engine's data with no model call, as a turn the conversation keeps
- CheckRunner.delete: removes an idle check, its conversation and all it produced
- CheckRunner.clone: copies an idle check, its conversation and all it produced into a new check,
  and leaves the source a check.cloned event naming the copy
- CheckRunner.archive and restore: the person closes an idle check, or reopens an archived one
- CheckRunner.save_finances: saves the figures the person types on a check's panel, refused while
  the check runs a turn
- CheckRunner.save_term: saves the term the person confirms on the term card, with a ceiling
  typed beside it, before the line that tells the model, refused while the check runs a turn
- CheckRunner.fail_interrupted: at startup, ends the turns a stopped process left running
- CheckRunner.drain and aclose: wait for or cancel the turns in flight

A check has at most one turn in flight; turns on different checks run concurrently. Every message
costs model calls, so a person may send at most turn_limit messages, or their override's number,
across all their checks, in any rolling window of the configured length, and deleting a check gives
none of them back. Turns live in this process's memory, so the agent runs as one replica.

A model turn that leaves the check with a recommendation and no payment ceiling ends with the
ceiling question, asked once per check by the runner rather than left to the model, so the
person always meets it after the first recommendation.

A turn streams the model's text to open pages as live message.delta events, each carrying the
whole text of its message so far, so a page that joins mid-reply catches up from the next one.
A reply that shows an English word the person did not write is withdrawn with a live
message.retracted at that word, since the graph has it rewritten before it is stored.
It stores each complete model message with text as message.assistant under the same message id,
so a page that replays the log sees complete messages only. A turn ends with turn.status idle,
preceded by turn.failed when it raised or was cut short by a restart; the error itself goes to the
log, never to the page. A cut-short turn leaves the thread at its last checkpoint, and the next
turn continues from there.
"""

import asyncio
import uuid
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState

from loan_agent.application.agent_graph import (
    AgentGraph,
    check_config,
    copy_conversation,
    delete_conversation,
    people_said,
    record_exchange,
)
from loan_agent.application.check_tools import CheckTools, ToolDeps, english_words
from loan_agent.application.finances_saving import save_finances
from loan_agent.application.market_answer import PRIME_MONTHS, market_answer
from loan_agent.domain.errors import (
    CheckArchivedError,
    CheckNotRestorableError,
    TurnConflictError,
    TurnLimitError,
)
from loan_agent.domain.models import Check, Finances, User
from loan_agent.ports.events import (
    CHART_SHOWN,
    CHECK_ARCHIVED,
    CHECK_CLONED,
    CHECK_RESTORED,
    MESSAGE_ASSISTANT,
    MESSAGE_DELTA,
    MESSAGE_RETRACTED,
    MESSAGE_USER,
    QUESTION_ASKED,
    TURN_FAILED,
    TURN_STATUS,
    EventSink,
)
from loan_agent.ports.repositories import CheckEventStore, CheckRepository

log = structlog.get_logger(__name__)

RUNNING = {"status": "running"}
IDLE = {"status": "idle"}

FAILURE_MESSAGE = "לא הצלחתי להשלים את התשובה. אפשר לנסות שוב."
CEILING_FIELD = "payment_ceiling"
CEILING_QUESTION = {
    "question": {"field": CEILING_FIELD, "offer_clone": False, "text": None, "choices": None},
    "lead_in": None,
}
# What the model's conversation records of a ceiling typed on the term card.
TERM_CARD_FOR_CEILING = (
    "The screen saved that payment ceiling as stated and showed a new term card for it: the "
    "shortest term at which every example track's worst-case payment fits the ceiling, or 84 "
    "months when none does. The person's answer to that card arrives as the next message."
)
# What the model's conversation records of the offer chip.
OFFER_FORM_SHOWN = (
    "The screen showed the offer form with nothing filled in. The person's answer arrives as "
    "the next message: a complete offer in words, at equal monthly payments."
)
# What the model's conversation records of the runner's question: the page words it itself.
CEILING_ASKED = (
    "The screen asked the person for their payment ceiling (field payment_ceiling), with a skip "
    "and a 'לא יודע/ת' choice; their answer arrives as the next message."
)
# The model reads this as the result of each unanswered tool call. The tool node runs one model
# message's calls concurrently, so another call from that message may have saved before one failed.
TOOL_CALL_OUTCOME_UNKNOWN = (
    "The outcome of this tool call is unknown: the previous turn ended with an error before its "
    "results were recorded, and the call may have completed. Before repeating a call that saves "
    "something (finances, a loan, an option), ask the person whether it already appears on "
    "their page."
)


@dataclass
class _Draft:
    """What one turn has streamed of the model's replies."""

    # The person's own messages in the check, whose English words a reply may repeat.
    people: list[str]
    # Key: model message id; value: the text its chunks have streamed so far.
    streamed: dict[str, str] = field(default_factory=dict)
    # Ids of replies withdrawn from the page for an English word.
    retracted: set[str] = field(default_factory=set)


class CheckRunner:
    def __init__(
        self,
        graph: AgentGraph,
        checks: CheckRepository,
        events: CheckEventStore,
        sink: EventSink,
        tool_deps: ToolDeps,
        turn_limit: int,
        turn_limit_overrides: Mapping[str, int],
        window: timedelta,
        clock: Callable[[], datetime],
    ) -> None:
        self._graph = graph
        self._checks = checks
        self._events = events
        self._sink = sink
        self._tool_deps = tool_deps
        self._turn_limit = turn_limit
        self._turn_limit_overrides = turn_limit_overrides
        self._window = window
        self._clock = clock
        # Key: check id. Value: its turn in flight; the strong reference keeps the task from being
        # garbage-collected.
        self._turns: dict[str, asyncio.Task[None]] = {}
        # Serializes a send's guards with the turn it starts, so a check never runs two turns and
        # concurrent sends cannot exceed the person's message cap.
        self._send_lock = asyncio.Lock()

    async def create(self, user: User) -> Check:
        check = Check(str(uuid.uuid4()), user.id, self._clock(), None, None, None, None, Finances())
        await self._checks.add(check)
        return check

    async def send(self, user: User, check_id: str, text: str) -> None:
        """Raises CheckNotFoundError for an unknown check or another person's, CheckArchivedError
        for an archived one, TurnConflictError while the check runs a turn, and TurnLimitError
        when the person's messages are used up."""
        await self._start(user, check_id, text, self._run)

    async def send_term_ceiling(
        self, user: User, check_id: str, text: str, payment_ceiling: Decimal
    ) -> None:
        """The term card's own ceiling: it counts as a message and raises as send does."""

        async def answer(user_id: str, check_id: str, text: str) -> None:
            await self._answer_term_ceiling(user_id, check_id, text, payment_ceiling)

        await self._start(user, check_id, text, answer)

    async def send_market_sample(self, user: User, check_id: str, text: str) -> None:
        """The page sends the market-data sample here, the person's own wording of it included;
        it counts as a message and raises as send does."""
        await self._start(user, check_id, text, self._answer_market)

    async def send_offer_sample(self, user: User, check_id: str, text: str) -> None:
        """The page sends the offer chip's sentence here; the offer form answers it with no model
        call. It counts as a message and raises as send does."""
        await self._start(user, check_id, text, self._answer_offer_sample)

    async def clone(self, user: User, check_id: str) -> Check:
        """Raises CheckNotFoundError for an unknown check or another person's, and
        TurnConflictError while the check runs a turn. The clone is open even when its source is
        archived."""
        async with self._send_lock:
            source = await self._checks.get(user.id, check_id)
            if check_id in self._turns:
                raise TurnConflictError(check_id)
            clone = Check(
                str(uuid.uuid4()),
                user.id,
                self._clock(),
                source.loan,
                source.term_months,
                source.payment_ceiling,
                source.ceiling_source,
                source.finances,
            )
            left_out = (CHECK_ARCHIVED, CHECK_RESTORED, CHECK_CLONED)
            await self._checks.clone(source.id, clone, left_out)
            await copy_conversation(self._graph, source.id, clone.id)
            await self._sink.emit(source.id, CHECK_CLONED, {"clone_id": clone.id})
            return clone

    async def delete(self, user: User, check_id: str) -> None:
        """Raises CheckNotFoundError for an unknown check or another person's, and
        TurnConflictError while the check runs a turn. The conversation goes first and is in
        another store, so a failure between the two leaves a check that can be deleted again,
        never a conversation that no check reaches."""
        async with self._send_lock:
            await self._checks.get(user.id, check_id)
            if check_id in self._turns:
                raise TurnConflictError(check_id)
            await delete_conversation(self._graph, check_id)
            await self._checks.delete(check_id, MESSAGE_USER, self._clock() - self._window)

    async def fail_interrupted(self) -> None:
        """Ends every turn whose latest turn.status is running while no turn of this process runs
        on the check: its process stopped mid-turn, and nothing else would end it. The turn may
        have stored other events after it started."""
        async with self._send_lock:
            for check_id in await self._events.checks_whose_latest(TURN_STATUS, RUNNING):
                if check_id not in self._turns:
                    log.warning("ending a turn interrupted by a restart", check_id=check_id)
                    await self._report_failure(check_id)

    async def drain(self) -> None:
        """Wait until no turn is in flight, including turns started while waiting."""
        while self._turns:
            await asyncio.wait(set(self._turns.values()))

    async def aclose(self) -> None:
        """Cancel the turns in flight; their threads stay at their last checkpoint."""
        turns = list(self._turns.values())
        for turn in turns:
            turn.cancel()
        await asyncio.gather(*turns, return_exceptions=True)

    def _limit_of(self, user: User) -> int:
        if user.email is None:
            return self._turn_limit
        return self._turn_limit_overrides.get(user.email.lower(), self._turn_limit)

    async def _require_message_left(self, user: User) -> None:
        now = self._clock()
        count, times = await self._events.count_since(user.id, MESSAGE_USER, now - self._window)
        limit = self._limit_of(user)
        if count >= limit:
            # The message whose expiry leaves limit - 1 in the window frees the next one; a message
            # stops counting once it is a full window old.
            freeing = times[count - limit]
            raise TurnLimitError(limit, freeing + self._window)

    async def save_finances(self, user: User, check_id: str, update: Mapping[str, object]) -> Check:
        """Raises CheckNotFoundError for an unknown check or another person's, CheckArchivedError
        for an archived one, TurnConflictError while the check runs a turn, and FinancesError or
        EngineError when the figures cannot be saved; nothing is saved then."""
        async with self._send_lock:
            await self._idle_open_check(user, check_id)
            return await save_finances(check_id, user.id, update, self._tool_deps)

    async def save_term(
        self, user: User, check_id: str, term_months: int, payment_ceiling: Decimal | None
    ) -> None:
        """Saves the term, and the ceiling as stated when one is given. Raises as save_finances
        does for an unknown, archived or busy check, and EngineError when an offer cannot be
        priced at the term; nothing is saved then, since the term's save is the one that can
        fail and it runs first."""
        async with self._send_lock:
            await self._idle_open_check(user, check_id)
            tools = CheckTools(user.id, check_id, self._tool_deps)
            await tools.save_term(term_months)
            if payment_ceiling is not None:
                await tools.set_ceiling(str(payment_ceiling))

    async def _idle_open_check(self, user: User, check_id: str) -> Check:
        check = await self._checks.get(user.id, check_id)
        if check.archived_at is not None:
            raise CheckArchivedError(check_id)
        if check_id in self._turns:
            raise TurnConflictError(check_id)
        return check

    async def archive(self, user: User, check_id: str) -> None:
        """Raises CheckNotFoundError for an unknown check or another person's, CheckArchivedError
        for an archived one, and TurnConflictError while the check runs a turn."""
        async with self._send_lock:
            await self._idle_open_check(user, check_id)
            now = self._clock()
            await self._checks.archive(check_id, now)
            await self._sink.emit(check_id, CHECK_ARCHIVED, {"archived_at": now.isoformat()})

    async def restore(self, user: User, check_id: str) -> None:
        """Raises CheckNotFoundError for an unknown check or another person's, and
        CheckNotRestorableError for a check that is not archived."""
        async with self._send_lock:
            check = await self._checks.get(user.id, check_id)
            if check.archived_at is None:
                raise CheckNotRestorableError(check_id)
            await self._checks.restore(check_id)
            await self._sink.emit(check_id, CHECK_RESTORED, {})

    async def _start(
        self,
        user: User,
        check_id: str,
        text: str,
        answer: Callable[[str, str, str], Coroutine[None, None, None]],
    ) -> None:
        """Records the message and runs answer as the check's turn in the background."""
        async with self._send_lock:
            await self._idle_open_check(user, check_id)
            await self._require_message_left(user)
            await self._sink.emit(check_id, MESSAGE_USER, {"text": text})
            await self._sink.emit(check_id, TURN_STATUS, RUNNING)
            turn = asyncio.create_task(answer(user.id, check_id, text))
            self._turns[check_id] = turn
            turn.add_done_callback(lambda done: self._forget(check_id, done))

    async def _run(self, user_id: str, check_id: str, text: str) -> None:
        config = check_config(user_id, check_id)
        try:
            unfinished = await self._close_unfinished_tool_calls(config)
            turn_input = MessagesState(messages=[*unfinished, HumanMessage(text)])
            earlier = (await self._graph.aget_state(config)).values.get("messages", [])
            draft = _Draft(people=[*people_said(earlier), text])
            async for part in self._graph.astream(
                turn_input, config, stream_mode=["messages", "updates"], version="v2"
            ):
                if part["type"] == "messages":
                    message, _metadata = part["data"]
                    await self._publish_text_so_far(check_id, message, draft)
                elif part["type"] == "updates":
                    await self._store_replies(check_id, part["data"])
                else:
                    raise AssertionError(f"unrequested stream part {part['type']!r}")
            await self._ask_ceiling_when_due(user_id, check_id, config)
        except Exception:
            log.exception("turn failed", check_id=check_id)
            await self._report_failure(check_id)
            return
        await self._sink.emit(check_id, TURN_STATUS, IDLE)

    async def _ask_ceiling_when_due(
        self, user_id: str, check_id: str, config: RunnableConfig
    ) -> None:
        """Asks for the payment ceiling once a check has a recommendation and no ceiling, unless
        the check was asked before (a clone keeps its source's asking) or the turn already ends
        with a question of the model's. The conversation records the question, so the model
        reads the next message as its answer."""
        check = await self._checks.get(user_id, check_id)
        if check.payment_ceiling is not None:
            return
        if await self._tool_deps.recommendations.latest(check_id) is None:
            return
        events = await self._events.list(check_id, 0)
        if events[-1].type == QUESTION_ASKED:
            return
        if any(
            event.type == QUESTION_ASKED
            and cast(Mapping[str, object], event.data["question"]).get("field") == CEILING_FIELD
            for event in events
        ):
            return
        await self._sink.emit(check_id, QUESTION_ASKED, CEILING_QUESTION)
        await record_exchange(self._graph, config, [AIMessage(CEILING_ASKED)])

    async def _answer_term_ceiling(
        self, user_id: str, check_id: str, text: str, payment_ceiling: Decimal
    ) -> None:
        config = check_config(user_id, check_id)
        try:
            unfinished = await self._close_unfinished_tool_calls(config)
            tools = CheckTools(user_id, check_id, self._tool_deps)
            await tools.set_ceiling(str(payment_ceiling))
            await tools.ask_term(None)
            exchange = [*unfinished, HumanMessage(text), AIMessage(TERM_CARD_FOR_CEILING)]
            await record_exchange(self._graph, config, exchange)
        except Exception:
            log.exception("term ceiling failed", check_id=check_id)
            await self._report_failure(check_id)
            return
        await self._sink.emit(check_id, TURN_STATUS, IDLE)

    async def _answer_offer_sample(self, user_id: str, check_id: str, text: str) -> None:
        config = check_config(user_id, check_id)
        try:
            unfinished = await self._close_unfinished_tool_calls(config)
            await CheckTools(user_id, check_id, self._tool_deps).ask_offer(None, [], None)
            exchange = [*unfinished, HumanMessage(text), AIMessage(OFFER_FORM_SHOWN)]
            await record_exchange(self._graph, config, exchange)
        except Exception:
            log.exception("offer sample failed", check_id=check_id)
            await self._report_failure(check_id)
            return
        await self._sink.emit(check_id, TURN_STATUS, IDLE)

    async def _answer_market(self, user_id: str, check_id: str, text: str) -> None:
        config = check_config(user_id, check_id)
        try:
            unfinished = await self._close_unfinished_tool_calls(config)
            reply, charts = market_answer(await self._tool_deps.engine.market_series(PRIME_MONTHS))
            message_id = str(uuid.uuid4())
            await self._sink.emit(
                check_id, MESSAGE_ASSISTANT, {"message_id": message_id, "text": reply}
            )
            for chart in charts:
                await self._sink.emit(check_id, CHART_SHOWN, chart)
            exchange = [*unfinished, HumanMessage(text), AIMessage(reply, id=message_id)]
            await record_exchange(self._graph, config, exchange)
        except Exception:
            log.exception("market answer failed", check_id=check_id)
            await self._report_failure(check_id)
            return
        await self._sink.emit(check_id, TURN_STATUS, IDLE)

    async def _report_failure(self, check_id: str) -> None:
        await self._sink.emit(check_id, TURN_FAILED, {"message": FAILURE_MESSAGE})
        await self._sink.emit(check_id, TURN_STATUS, IDLE)

    async def _close_unfinished_tool_calls(self, config: RunnableConfig) -> list[ToolMessage]:
        """Answers the tool calls of a turn that ended inside the tool node, since a model
        provider refuses a conversation whose tool call has no result. The node records no result
        when one call raises, though its other calls may have completed and saved."""
        snapshot = await self._graph.aget_state(config)
        if not snapshot.values:
            return []
        last = snapshot.values["messages"][-1]
        if not isinstance(last, AIMessage):
            return []
        closing = []
        for call in last.tool_calls:
            assert call["id"] is not None, "a tool call the model made always carries its id"
            closing.append(
                ToolMessage(TOOL_CALL_OUTCOME_UNKNOWN, tool_call_id=call["id"], status="error")
            )
        return closing

    async def _publish_text_so_far(self, check_id: str, chunk: BaseMessage, draft: _Draft) -> None:
        """Publishes a reply's text so far, until an English word the person did not write
        appears in it: the graph will have the reply rewritten, so the page drops it then and
        is sent none of the rest."""
        said = _model_text(chunk)
        if said is None or said["message_id"] in draft.retracted:
            return
        message_id = said["message_id"]
        text = draft.streamed.get(message_id, "") + said["text"]
        draft.streamed[message_id] = text
        if english_words(text, draft.people):
            draft.retracted.add(message_id)
            await self._sink.publish_live(check_id, MESSAGE_RETRACTED, {"message_id": message_id})
            return
        await self._sink.publish_live(
            check_id, MESSAGE_DELTA, {"message_id": message_id, "text": text}
        )

    async def _store_replies(self, check_id: str, update: Mapping[str, MessagesState]) -> None:
        for node_update in update.values():
            for message in node_update["messages"]:
                said = _model_text(message)
                if said is not None:
                    await self._sink.emit(check_id, MESSAGE_ASSISTANT, said)

    def _forget(self, check_id: str, turn: asyncio.Task[None]) -> None:
        """A turn that raised while reporting its own outcome is logged, never dropped silently."""
        assert self._turns[check_id] is turn, "a check's turns never overlap"
        del self._turns[check_id]
        if not turn.cancelled() and turn.exception() is not None:
            log.error("turn crashed while reporting its outcome", exc_info=turn.exception())


def _model_text(message: BaseMessage) -> dict[str, str] | None:
    """The message id and text of a model message or chunk that has text; None for tool results
    and for chunks that carry only tool calls."""
    if not isinstance(message, AIMessage) or not message.text:
        return None
    assert message.id is not None, "the chat model stamps every message and chunk with an id"
    return {"message_id": message.id, "text": message.text}
