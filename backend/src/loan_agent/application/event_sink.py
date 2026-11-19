"""Records each check event in the durable log, then fans it out to the check's live subscribers;
live-only events skip the log."""

from collections.abc import Mapping
from typing import Any

from loan_agent.ports.events import EventBus
from loan_agent.ports.repositories import CheckEventStore


def check_channel(check_id: str) -> str:
    """The bus channel that carries one check's events."""
    return f"check:{check_id}"


class CheckEventSink:
    def __init__(self, store: CheckEventStore, bus: EventBus) -> None:
        self._store = store
        self._bus = bus

    async def emit(self, check_id: str, type: str, data: Mapping[str, object]) -> int:
        """Persists before publishing, so a subscriber never sees an event the log does not hold;
        the published event carries its seq, so a page that replayed the log can skip it, and
        the time the log stamped it with."""
        stored = await self._store.append(check_id, type, data)
        timed = {"seq": stored.seq, "at": stored.created_at}
        await self._bus.publish(check_channel(check_id), _wire(type, data) | timed)
        return stored.seq

    async def publish_live(self, check_id: str, type: str, data: Mapping[str, object]) -> None:
        await self._bus.publish(check_channel(check_id), _wire(type, data))

    async def latest(self, check_id: str, type: str) -> Mapping[str, object] | None:
        of_type = [event for event in await self._store.list(check_id, 0) if event.type == type]
        return of_type[-1].data if of_type else None

    async def since(self, check_id: str, type: str, after: str) -> list[Mapping[str, object]]:
        events = await self._store.list(check_id, 0)
        start = max((i for i, event in enumerate(events) if event.type == after), default=-1)
        return [event.data for event in events[start + 1 :] if event.type == type]


def _wire(type: str, data: Mapping[str, object]) -> dict[str, Any]:
    return {"type": type, "data": dict(data)}
