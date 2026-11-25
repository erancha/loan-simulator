"""The check's event stream: stored events replayed after Last-Event-ID, then live events, with live
reply fragments framed without an id so a reconnect never resumes from one.

Stream tests run the app under a real uvicorn server: TestClient buffers a response until the app
returns, and an event stream only returns when its client disconnects."""

import asyncio
import json
import signal
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Any

import httpx
import pytest
import uvicorn
from app_world import DANA_TOKEN, World
from fastapi import FastAPI
from langchain_core.messages import AIMessage

from fakes import NOW, Clock, InMemoryCheckEventStore, InMemoryCheckRepository
from loan_agent.adapters.memory_bus import InMemoryEventBus
from loan_agent.application.event_sink import CheckEventSink
from loan_agent.domain.models import Check, Finances
from loan_agent.platform.api.auth import COOKIE
from loan_agent.platform.api.events import check_frames, live_frame, stored_frame
from loan_agent.platform.app import signal_shutdown
from loan_agent.ports.repositories import StoredEvent

DEADLINE_SECONDS = 5.0
FIRST_REPLY = "שלום, מה ההכנסה החודשית שלך?"
SECOND_REPLY = "ומה מחיר הרכב?"


@contextmanager
def serve(app: FastAPI) -> Iterator[httpx.Client]:
    """A client of the app served on a free local port, signed in as Dana; the server stops on
    exit."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, timeout_graceful_shutdown=2))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + DEADLINE_SECONDS
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.01)
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            timeout=DEADLINE_SECONDS,
            cookies={COOKIE: DANA_TOKEN},
        ) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(DEADLINE_SECONDS)
        assert not thread.is_alive(), "uvicorn did not stop"


def frames(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Parsed SSE frames, "id" present only when the frame carries one; comments are skipped."""
    fields: dict[str, str] = {}
    for line in lines:
        if line.startswith(":"):
            continue
        if line:
            name, _, value = line.partition(": ")
            fields[name] = value
            continue
        if fields:
            frame: dict[str, Any] = {"type": fields["event"], "data": json.loads(fields["data"])}
            if "id" in fields:
                frame["id"] = int(fields["id"])
            yield frame
            fields = {}


def is_idle(frame: Mapping[str, Any]) -> bool:
    return frame["type"] == "turn.status" and frame["data"]["status"] == "idle"


def until(
    stream: Iterator[dict[str, Any]], last: Callable[[Mapping[str, Any]], bool]
) -> list[dict[str, Any]]:
    read: list[dict[str, Any]] = []
    for frame in stream:
        read.append(frame)
        if last(frame):
            return read
    raise AssertionError("the stream ended early")


def wait_until_idle(world: World, check_id: str) -> None:
    deadline = time.monotonic() + DEADLINE_SECONDS
    while not is_idle(vars(world.events.rows[check_id][-1])):
        assert time.monotonic() < deadline, "the turn did not end"
        time.sleep(0.01)


def test_a_stored_frame_carries_its_seq_and_one_line_of_json_with_its_time() -> None:
    frame = stored_frame(3, "message.assistant", {"text": "שלום\nworld"}, NOW)
    assert frame == (
        "id: 3\nevent: message.assistant\n"
        'data: {"text": "שלום\\nworld", "at": "2026-10-27T09:00:00+00:00"}\n\n'
    )


def test_a_live_frame_has_no_id() -> None:
    frame = live_frame("message.delta", {"message_id": "m1", "text": "של"})
    assert frame == 'event: message.delta\ndata: {"message_id": "m1", "text": "של"}\n\n'


def test_the_stream_replays_after_last_event_id_then_streams_live(
    world: World, public_key: Path
) -> None:
    world.replies(AIMessage(FIRST_REPLY), AIMessage(SECOND_REPLY))
    with serve(world.app(public_key)) as client:
        check_id = client.post("/api/checks").json()["id"]
        client.post(f"/api/checks/{check_id}/messages", json={"text": "אני רוצה רכב"})
        wait_until_idle(world, check_id)

        url = f"/api/checks/{check_id}/events"
        with client.stream("GET", url, headers={"Last-Event-ID": "3"}) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            stream = frames(response.iter_lines())
            replayed = until(stream, is_idle)
            client.post(f"/api/checks/{check_id}/messages", json={"text": "תקציב 4,000"})
            live = until(stream, is_idle)

        with client.stream("GET", url, headers={"Last-Event-ID": "8"}) as response:
            resumed = until(frames(response.iter_lines()), is_idle)

    assert [(frame["id"], frame["type"]) for frame in replayed] == [
        (4, "message.assistant"),
        (5, "turn.status"),
    ]
    assert replayed[0]["data"]["text"] == FIRST_REPLY
    deltas = [frame for frame in live if frame["type"] == "message.delta"]
    steps = [frame for frame in live if frame["type"] == "turn.step"]
    stored = [frame for frame in live if frame["type"] not in ("message.delta", "turn.step")]
    assert len(deltas) > 1
    assert [frame["data"] for frame in steps] == [{"step": 1, "tools": []}]
    assert not [frame for frame in deltas + steps if "id" in frame or "at" in frame["data"]]
    assert {frame["data"]["at"] for frame in stored} == {NOW.isoformat()}
    assert deltas[-1]["data"]["text"] == SECOND_REPLY
    assert [(frame["id"], frame["type"]) for frame in stored] == [
        (6, "message.user"),
        (7, "message.counted"),
        (8, "turn.status"),
        (9, "message.assistant"),
        (10, "turn.status"),
    ]
    assert {frame["data"]["message_id"] for frame in deltas} == {stored[3]["data"]["message_id"]}
    assert [(frame["id"], frame["type"]) for frame in resumed] == [
        (9, "message.assistant"),
        (10, "turn.status"),
    ]


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


class RacingStore(InMemoryCheckEventStore):
    """Emits one event just before the replay snapshot is taken and one just after it, then
    publishes a live-only event."""

    def __init__(self) -> None:
        checks = InMemoryCheckRepository()
        checks.rows["c1"] = Check("c1", "1001", NOW, None, None, None, None, Finances())
        super().__init__(checks, Clock())
        self.bus = InMemoryEventBus()
        self.sink = CheckEventSink(self, self.bus)

    async def list(self, check_id: str, after_seq: int) -> list[StoredEvent]:
        await self.sink.emit(check_id, "before.snapshot", {})
        snapshot = await super().list(check_id, after_seq)
        await self.sink.emit(check_id, "after.snapshot", {})
        await self.sink.publish_live(check_id, "message.delta", {"message_id": "m1", "text": "x"})
        return snapshot


async def test_events_racing_the_replay_arrive_once_each() -> None:
    store = RacingStore()
    await store.append("c1", "persisted", {})
    stream = check_frames(
        ConnectedRequest(),  # type: ignore[arg-type]
        store,
        store.bus,
        "c1",
        0,
        asyncio.Event(),
    )

    sent = [await anext(stream) for _ in range(4)]
    await stream.aclose()

    assert sent == [
        stored_frame(1, "persisted", {}, NOW),
        stored_frame(2, "before.snapshot", {}, NOW),
        stored_frame(3, "after.snapshot", {}, NOW),
        live_frame("message.delta", {"message_id": "m1", "text": "x"}),
    ]


class CompletingStore(InMemoryCheckEventStore):
    """Stores message m1 complete while the stream is between its subscribe and its replay, so
    a fragment of m1 published before it is already queued, followed by a fragment of m2."""

    def __init__(self) -> None:
        checks = InMemoryCheckRepository()
        checks.rows["c1"] = Check("c1", "1001", NOW, None, None, None, None, Finances())
        super().__init__(checks, Clock())
        self.bus = InMemoryEventBus()
        self.sink = CheckEventSink(self, self.bus)

    async def list(self, check_id: str, after_seq: int) -> list[StoredEvent]:
        await self.sink.publish_live(check_id, "message.delta", {"message_id": "m1", "text": "ש"})
        await self.sink.emit(check_id, "message.assistant", {"message_id": "m1", "text": "שלום"})
        snapshot = await super().list(check_id, after_seq)
        await self.sink.publish_live(check_id, "message.delta", {"message_id": "m2", "text": "ו"})
        return snapshot


async def test_fragments_of_a_message_the_replay_sent_complete_are_dropped() -> None:
    store = CompletingStore()
    stream = check_frames(
        ConnectedRequest(),  # type: ignore[arg-type]
        store,
        store.bus,
        "c1",
        0,
        asyncio.Event(),
    )

    sent = [await anext(stream) for _ in range(2)]
    await stream.aclose()

    assert sent == [
        stored_frame(1, "message.assistant", {"message_id": "m1", "text": "שלום"}, NOW),
        live_frame("message.delta", {"message_id": "m2", "text": "ו"}),
    ]


async def test_the_stream_ends_soon_after_shutdown_is_signalled() -> None:
    store = RacingStore()
    shutdown = asyncio.Event()
    stream = check_frames(
        ConnectedRequest(),  # type: ignore[arg-type]
        store,
        InMemoryEventBus(),
        "c1",
        0,
        shutdown,
    )
    assert await anext(stream) == stored_frame(1, "before.snapshot", {}, NOW)

    pending = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.05)
    assert not pending.done()
    shutdown.set()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pending, timeout=1)


async def test_a_quiet_stream_sends_keepalive_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("loan_agent.platform.api.events.KEEPALIVE_SECONDS", 0.01)
    store = InMemoryCheckEventStore(InMemoryCheckRepository(), Clock())
    stream = check_frames(
        ConnectedRequest(),  # type: ignore[arg-type]
        store,
        InMemoryEventBus(),
        "c1",
        0,
        asyncio.Event(),
    )
    assert await asyncio.wait_for(anext(stream), timeout=1) == ": keepalive\n\n"
    await stream.aclose()


async def test_signal_shutdown_sets_the_event_and_chains_the_prior_handler() -> None:
    received: list[int] = []

    def prior(sig: int, frame: FrameType | None) -> None:
        received.append(sig)

    shutdown = asyncio.Event()
    previous = signal.signal(signal.SIGTERM, prior)
    try:
        with signal_shutdown(shutdown):
            signal.raise_signal(signal.SIGTERM)
            await asyncio.wait_for(shutdown.wait(), timeout=1)
        assert received == [signal.SIGTERM]
        assert signal.getsignal(signal.SIGTERM) is prior
    finally:
        signal.signal(signal.SIGTERM, previous)
