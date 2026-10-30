"""Event delivery ports: how the application reports what happens on a check to the person's page.

- EventSink: stored events, replayed when the page reconnects, and live-only events
- EventBus: fan-out of events to the subscribers of a channel, in this process
- The event types a check's log and stream carry, named once for every emitter

Event data is JSON-ready: money as decimal strings, dates and datetimes as ISO strings.
"""

import asyncio
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable

MESSAGE_USER = "message.user"
MESSAGE_DELTA = "message.delta"
MESSAGE_ASSISTANT = "message.assistant"
TURN_STATUS = "turn.status"
TURN_FAILED = "turn.failed"
PROFILE_UPDATED = "profile.updated"
GOAL_SET = "goal.set"
OPTION_SAVED = "option.saved"
RECOMMENDATION_PRESENTED = "recommendation.presented"
QUESTION_ASKED = "question.asked"
CHART_SHOWN = "chart.shown"


@runtime_checkable
class EventSink(Protocol):
    async def emit(self, check_id: str, type: str, data: Mapping[str, object]) -> int:
        """Stores the event, then publishes it; returns its sequence number within the check."""
        ...

    async def publish_live(self, check_id: str, type: str, data: Mapping[str, object]) -> None:
        """Publishes the event to open pages without storing it."""
        ...


class EventBus(Protocol):
    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        """Delivers the event to every current subscriber of the channel."""
        ...

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[asyncio.Queue[dict[str, Any]]]:
        """Subscribes for the context's duration; the queue receives events published meanwhile."""
        ...
