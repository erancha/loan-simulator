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
# Live only: a streamed reply the page drops, since it will be rewritten.
MESSAGE_RETRACTED = "message.retracted"
MESSAGE_ASSISTANT = "message.assistant"
TURN_STATUS = "turn.status"
TURN_FAILED = "turn.failed"
LOAN_SET = "loan.set"
TERM_SET = "term.set"
CEILING_SET = "ceiling.set"
FINANCES_UPDATED = "finances.updated"
OPTION_SAVED = "option.saved"
# A check's examples go once it holds a real offer, with a recommendation that names one.
EXAMPLES_REMOVED = "examples.removed"
# A new loan amount or term withdrew what no longer holds: the options of another amount, and the
# recommendation of another amount or term.
OPTIONS_REMOVED = "options.removed"
RECOMMENDATION_PRESENTED = "recommendation.presented"
# An offer whose type awaits its lender's answer; emitted again when a later message changes it.
OFFER_AWAITING = "offer.awaiting"
OFFER_IDENTIFIED = "offer.identified"
OFFER_UNRECOGNIZED = "offer.unrecognized"
# An awaiting offer became a saved offer, with the reading it was saved by: the one the person
# confirmed, or the one a later detail identified, which its card may not hold.
OFFER_SETTLED = "offer.settled"
# An awaiting offer quoted for less than the check's loan left the check: its lender does not
# lend the loan amount on the same terms.
OFFER_DROPPED = "offer.dropped"
QUESTION_ASKED = "question.asked"
CHART_SHOWN = "chart.shown"
SCENARIO_SHOWN = "scenario.shown"
CHECK_ARCHIVED = "check.archived"
CHECK_RESTORED = "check.restored"
CHECK_CLONED = "check.cloned"


@runtime_checkable
class EventSink(Protocol):
    async def emit(self, check_id: str, type: str, data: Mapping[str, object]) -> int:
        """Stores the event, then publishes it; returns its sequence number within the check."""
        ...

    async def publish_live(self, check_id: str, type: str, data: Mapping[str, object]) -> None:
        """Publishes the event to open pages without storing it."""
        ...

    async def latest(self, check_id: str, type: str) -> Mapping[str, object] | None:
        """The data of the check's latest stored event of this type; None when it has none."""
        ...

    async def since(self, check_id: str, type: str, after: str) -> list[Mapping[str, object]]:
        """The data of the check's stored events of this type after its latest event of the type
        after, oldest first; all of them when it has none of that one."""
        ...


class EventBus(Protocol):
    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        """Delivers the event to every current subscriber of the channel."""
        ...

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[asyncio.Queue[dict[str, Any]]]:
        """Subscribes for the context's duration; the queue receives events published meanwhile."""
        ...
