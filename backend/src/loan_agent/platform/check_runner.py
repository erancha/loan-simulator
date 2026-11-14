"""Runs conversation turns on checks and reports every step of a turn as a check event.

Core building blocks:
- CheckRunner.create: a new, empty check for the signed-in person
- CheckRunner.send: records the person's message and runs the turn as a background task
- CheckRunner.delete: removes an idle check, its conversation and all it produced
- CheckRunner.clone: copies an idle check, its conversation and all it produced into a new check
- CheckRunner.archive and restore: the person closes an idle check, or reopens one whose
  figures still match the profile
- CheckRunner.fail_interrupted: at startup, ends the turns a stopped process left running
- CheckRunner.drain and aclose: wait for or cancel the turns in flight

A check has at most one turn in flight; turns on different checks run concurrently. Every message
costs model calls, so a person may send at most turn_limit messages, or their override's number,
across all their checks, in any rolling window of the configured length, and deleting a check gives
none of them back. Turns live in this process's memory, so the agent runs as one replica.

A turn streams the model's text to open pages as live message.delta events, each carrying the
whole text of its message so far, so a page that joins mid-reply catches up from the next one.
It stores each complete model message with text as message.assistant under the same message id,
so a page that replays the log sees complete messages only. A turn ends with turn.status idle,
preceded by turn.failed when it raised or was cut short by a restart; the error itself goes to the
log, never to the page. A cut-short turn leaves the thread at its last checkpoint, and the next
turn continues from there.

A turn that ends by archiving its check (a profile change replaced the figures its recommendation
was computed from) continues in a new check with the same goal: the old check's log names the new
one in check.continued, the new one's log opens with check.follows, naming the old one and the
changes that archived it, and the new check runs a turn on the person's same message. The new
check's turn skips the cap check, but its copy of the message is logged like any other, so the
person's count holds the message twice.
"""

import asyncio
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import MessagesState

from loan_agent.application.agent_graph import (
    AgentGraph,
    archived_the_check,
    check_config,
    copy_conversation,
    delete_conversation,
    last_message,
)
from loan_agent.application.profile_saving import manual_archive_data
from loan_agent.domain.errors import (
    CheckArchivedError,
    CheckNotRestorableError,
    TurnConflictError,
    TurnLimitError,
)
from loan_agent.domain.models import Check, User
from loan_agent.ports.events import (
    CHECK_ARCHIVED,
    CHECK_CONTINUED,
    CHECK_FOLLOWS,
    CHECK_RESTORED,
    GOAL_SET,
    MESSAGE_ASSISTANT,
    MESSAGE_DELTA,
    MESSAGE_USER,
    TURN_FAILED,
    TURN_STATUS,
    EventSink,
)
from loan_agent.ports.repositories import CheckEventStore, CheckRepository, ProfileRepository

log = structlog.get_logger(__name__)

RUNNING = {"status": "running"}
IDLE = {"status": "idle"}

FAILURE_MESSAGE = "לא הצלחתי להשלים את התשובה. אפשר לנסות שוב."
# The model reads this as the result of each unanswered tool call. The tool node runs one model
# message's calls concurrently, so another call from that message may have saved before one failed.
TOOL_CALL_OUTCOME_UNKNOWN = (
    "The outcome of this tool call is unknown: the previous turn ended with an error before its "
    "results were recorded, and the call may have completed. Before repeating a call that saves "
    "something (a profile, a goal, an option), ask the person whether it already appears on "
    "their page."
)


class CheckRunner:
    def __init__(
        self,
        graph: AgentGraph,
        checks: CheckRepository,
        profiles: ProfileRepository,
        events: CheckEventStore,
        sink: EventSink,
        turn_limit: int,
        turn_limit_overrides: Mapping[str, int],
        window: timedelta,
        clock: Callable[[], datetime],
    ) -> None:
        self._graph = graph
        self._checks = checks
        self._profiles = profiles
        self._events = events
        self._sink = sink
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
        check = Check(str(uuid.uuid4()), user.id, self._clock(), None, None)
        await self._checks.add(check)
        return check

    async def send(self, user: User, check_id: str, text: str) -> None:
        """Raises CheckNotFoundError for an unknown check or another person's, CheckArchivedError
        for an archived one, TurnConflictError while the check runs a turn, and TurnLimitError
        when the person's messages are used up."""
        async with self._send_lock:
            check = await self._checks.get(user.id, check_id)
            if check.archived_at is not None:
                raise CheckArchivedError(check_id)
            if check_id in self._turns:
                raise TurnConflictError(check_id)
            await self._require_message_left(user)
            await self._start(user.id, check_id, text)

    async def clone(self, user: User, check_id: str) -> Check:
        """Raises CheckNotFoundError for an unknown check or another person's, and
        TurnConflictError while the check runs a turn. The clone is open even when its source is
        archived; it then reads as stale, recommended from an older profile."""
        async with self._send_lock:
            source = await self._checks.get(user.id, check_id)
            if check_id in self._turns:
                raise TurnConflictError(check_id)
            clone = Check(
                str(uuid.uuid4()), user.id, self._clock(), source.goal, source.profile_snapshot_at
            )
            left_out = (CHECK_ARCHIVED, CHECK_CONTINUED, CHECK_RESTORED)
            await self._checks.clone(source.id, clone, left_out)
            await copy_conversation(self._graph, source.id, clone.id)
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

    async def archive(self, user: User, check_id: str) -> None:
        """Raises CheckNotFoundError for an unknown check or another person's, CheckArchivedError
        for an archived one, and TurnConflictError while the check runs a turn."""
        async with self._send_lock:
            check = await self._checks.get(user.id, check_id)
            if check.archived_at is not None:
                raise CheckArchivedError(check_id)
            if check_id in self._turns:
                raise TurnConflictError(check_id)
            now = self._clock()
            await self._checks.archive(check_id, now)
            await self._sink.emit(check_id, CHECK_ARCHIVED, manual_archive_data(now))

    async def restore(self, user: User, check_id: str) -> None:
        """Raises CheckNotFoundError for an unknown check or another person's, and
        CheckNotRestorableError for an open check or one whose figures the profile no longer
        has."""
        async with self._send_lock:
            check = await self._checks.get(user.id, check_id)
            _, profile_updated_at = await self._profiles.get(user.id)
            if not check.is_restorable(profile_updated_at):
                raise CheckNotRestorableError(check_id)
            await self._checks.restore(check_id)
            await self._sink.emit(check_id, CHECK_RESTORED, {})

    async def _start(self, user_id: str, check_id: str, text: str) -> None:
        """Runs a turn on a check with no turn in flight."""
        await self._sink.emit(check_id, MESSAGE_USER, {"text": text})
        await self._sink.emit(check_id, TURN_STATUS, RUNNING)
        turn = asyncio.create_task(self._run(user_id, check_id, text))
        self._turns[check_id] = turn
        turn.add_done_callback(lambda done: self._forget(check_id, done))

    async def _continue_in_new_check(self, user_id: str, archived_id: str, text: str) -> None:
        archived = await self._checks.get(user_id, archived_id)
        check = Check(str(uuid.uuid4()), user_id, self._clock(), archived.goal, None)
        await self._checks.add(check)
        archive = next(
            event
            for event in reversed(await self._events.list(archived_id, 0))
            if event.type == CHECK_ARCHIVED
        )
        follows = {"check_id": archived_id, "changes": archive.data["changes"]}
        await self._sink.emit(check.id, CHECK_FOLLOWS, follows)
        if check.goal is not None:
            goal = {"purpose": check.goal.purpose, "price": str(check.goal.price)}
            await self._sink.emit(check.id, GOAL_SET, goal)
        await self._sink.emit(archived_id, CHECK_CONTINUED, {"check_id": check.id})
        await self._start(user_id, check.id, text)

    async def _run(self, user_id: str, check_id: str, text: str) -> None:
        config = check_config(user_id, check_id)
        try:
            unfinished = await self._close_unfinished_tool_calls(config)
            turn_input = MessagesState(messages=[*unfinished, HumanMessage(text)])
            # Key: model message id; value: the text its chunks have streamed so far.
            streamed: dict[str, str] = {}
            async for part in self._graph.astream(
                turn_input, config, stream_mode=["messages", "updates"], version="v2"
            ):
                if part["type"] == "messages":
                    message, _metadata = part["data"]
                    await self._publish_text_so_far(check_id, message, streamed)
                elif part["type"] == "updates":
                    await self._store_replies(check_id, part["data"])
                else:
                    raise AssertionError(f"unrequested stream part {part['type']!r}")
            if archived_the_check(await last_message(self._graph, check_id)):
                await self._continue_in_new_check(user_id, check_id, text)
        except Exception:
            log.exception("turn failed", check_id=check_id)
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

    async def _publish_text_so_far(
        self, check_id: str, chunk: BaseMessage, streamed: dict[str, str]
    ) -> None:
        said = _model_text(chunk)
        if said is not None:
            message_id = said["message_id"]
            streamed[message_id] = streamed.get(message_id, "") + said["text"]
            so_far = {"message_id": message_id, "text": streamed[message_id]}
            await self._sink.publish_live(check_id, MESSAGE_DELTA, so_far)

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
