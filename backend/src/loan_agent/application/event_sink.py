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
        the published event carries its seq so a page that replayed the log can skip it."""
        seq = await self._store.append(check_id, type, data)
        await self._bus.publish(check_channel(check_id), _wire(type, data) | {"seq": seq})
        return seq

    async def publish_live(self, check_id: str, type: str, data: Mapping[str, object]) -> None:
        await self._bus.publish(check_channel(check_id), _wire(type, data))


def _wire(type: str, data: Mapping[str, object]) -> dict[str, Any]:
    return {"type": type, "data": dict(data)}
