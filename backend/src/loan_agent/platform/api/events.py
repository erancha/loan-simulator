"""Server-sent event stream of one check: its stored history, then live events.

The stream subscribes to the check's bus channel before reading the log, so an event stored
between the two arrives on the queue; queued events the replay already sent are skipped by
sequence number. The log assigns sequences in commit order without gaps, so a replay holds every
sequence up to its last. A reconnecting browser sends Last-Event-ID and gets only what follows it.
Queued message.delta events of a message the replay already sent complete are dropped, so the
stream never sends a partial text after its complete message.

Stored events are framed with their sequence number as the frame's id and their time in the
frame's JSON. Live-only events (the reply's message.delta events) are framed without an id, so
the browser's Last-Event-ID always names a stored event and a reconnect resumes from the log.
Only the check's owner may subscribe; the session cookie identifies them, since the browser's
event-stream object sends no headers.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from loan_agent.application.event_sink import check_channel
from loan_agent.platform.api.auth import CurrentUser
from loan_agent.platform.dependencies import Deps, Shutdown
from loan_agent.ports.events import MESSAGE_ASSISTANT, MESSAGE_DELTA, EventBus
from loan_agent.ports.repositories import CheckEventStore

KEEPALIVE_SECONDS = 15.0
KEEPALIVE_FRAME = ": keepalive\n\n"

router = APIRouter()


def stored_frame(seq: int, event_type: str, data: Mapping[str, object], at: datetime) -> str:
    """The event's time rides in the frame's JSON as at, beside the event's own data, so the page
    can date what it shows; no event's data has a key of that name."""
    assert "at" not in data, f"{event_type} data already has an at key"
    return f"id: {seq}\n{live_frame(event_type, {**data, 'at': at.isoformat()})}"


def live_frame(event_type: str, data: Mapping[str, object]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def check_frames(
    request: Request,
    store: CheckEventStore,
    bus: EventBus,
    check_id: str,
    after_seq: int,
    shutdown: asyncio.Event,
) -> AsyncIterator[str]:
    """Runs until the client disconnects or the app shuts down; an idle turn does not end the
    stream, since the person may send another message."""
    async with bus.subscribe(check_channel(check_id)) as queue:
        replayed_through = after_seq
        replayed_messages: set[object] = set()
        for event in await store.list(check_id, after_seq):
            yield stored_frame(event.seq, event.type, event.data, event.created_at)
            replayed_through = event.seq
            if event.type == MESSAGE_ASSISTANT:
                replayed_messages.add(event.data["message_id"])
        stopping = asyncio.ensure_future(shutdown.wait())
        receiving: asyncio.Future[dict[str, Any]] | None = None
        try:
            while not await request.is_disconnected():
                if receiving is None:
                    receiving = asyncio.ensure_future(queue.get())
                waiting: set[asyncio.Future[Any]] = {receiving, stopping}
                done, _ = await asyncio.wait(
                    waiting, timeout=KEEPALIVE_SECONDS, return_when=asyncio.FIRST_COMPLETED
                )
                if stopping in done:
                    return
                if receiving not in done:
                    yield KEEPALIVE_FRAME
                    continue
                live, receiving = receiving.result(), None
                if "seq" not in live:
                    stale = (
                        live["type"] == MESSAGE_DELTA
                        and live["data"]["message_id"] in replayed_messages
                    )
                    if not stale:
                        yield live_frame(live["type"], live["data"])
                elif live["seq"] > replayed_through:
                    yield stored_frame(live["seq"], live["type"], live["data"], live["at"])
        finally:
            stopping.cancel()
            if receiving is not None:
                receiving.cancel()


@router.get("/api/checks/{check_id}/events")
async def check_events(
    check_id: str,
    request: Request,
    deps: Deps,
    shutdown: Shutdown,
    user: CurrentUser,
    last_event_id: Annotated[int | None, Header()] = None,
) -> StreamingResponse:
    """Last-Event-ID is absent on a first connection, which replays the whole log."""
    await deps.checks.get(user.id, check_id)
    after_seq = 0 if last_event_id is None else last_event_id
    return StreamingResponse(
        check_frames(request, deps.events, deps.bus, check_id, after_seq, shutdown),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
