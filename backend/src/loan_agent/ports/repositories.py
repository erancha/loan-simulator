"""Persistence ports: what the application needs to keep and read back.

- CheckRepository, OptionRepository, RecommendationRepository: a check and what it produced
- CheckEventStore: the per-check event log, also the source of the per-person message count
- StoredEvent: one logged event as read back

Every method that takes a user id answers only for that person's rows.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from loan_agent.domain.models import (
    CeilingSource,
    Check,
    Finances,
    LoanRequest,
    Option,
    Recommendation,
)

# Aliases: a list method in a class body shadows the builtin for the annotations after it.
EventTimes = list[datetime]
"""Creation times in ascending order."""
CheckIds = list[str]


@dataclass(frozen=True)
class StoredEvent:
    seq: int
    """1-based, gapless within one check."""
    type: str
    data: Mapping[str, object]
    created_at: datetime


@runtime_checkable
class CheckRepository(Protocol):
    async def add(self, check: Check) -> None: ...

    async def get(self, user_id: str, check_id: str) -> Check:
        """Raises CheckNotFoundError for an unknown id and for another person's check."""
        ...

    async def list(self, user_id: str) -> list[Check]:
        """Newest first."""
        ...

    async def delete(self, check_id: str, kept_type: str, kept_since: datetime) -> None:
        """Deletes the check, its options, its recommendation and its events together. Only the
        person and the time of its kept_type events after kept_since stay, for count_since; they
        go at a later delete that finds them older than its own kept_since."""
        ...

    async def set_loan(self, check_id: str, loan: LoanRequest) -> None: ...

    async def set_term(self, check_id: str, term_months: int) -> None: ...

    async def set_ceiling(self, check_id: str, ceiling: Decimal, source: CeilingSource) -> None: ...

    async def set_finances(self, check_id: str, finances: Finances) -> None: ...

    async def latest_finances(self, user_id: str, other_than: str) -> Finances | None:
        """The complete finances of the person's most recently created check other than
        other_than, for the question whether to reuse them; None when no other check has both
        figures."""
        ...

    async def archive(self, check_id: str, at: datetime) -> None: ...

    async def restore(self, check_id: str) -> None:
        """Reopens an archived check."""
        ...

    async def clone(self, source_id: str, clone: Check, left_out: Collection[str]) -> None:
        """Adds the clone, which carries the loan, term, ceiling and finances it starts with, and
        copies of the source's options, recommendation and events, all in one transaction. Option
        ids stay as they are, since the conversation names them. Events of the left_out types are
        not copied; the copies keep their times and data, are numbered from 1, and never count
        in count_since."""
        ...


@runtime_checkable
class OptionRepository(Protocol):
    async def add(self, option: Option) -> None: ...

    async def replace(self, option: Option) -> None:
        """Replaces the check's option of the same id; raises KeyError when it has none."""
        ...

    async def list(self, check_id: str) -> list[Option]:
        """Oldest first."""
        ...

    async def get(self, check_id: str, option_id: str) -> Option:
        """Raises KeyError for an option the check does not have."""
        ...


@runtime_checkable
class RecommendationRepository(Protocol):
    async def save(self, recommendation: Recommendation) -> None:
        """Replaces the check's previous recommendation."""
        ...

    async def latest(self, check_id: str) -> Recommendation | None: ...


@runtime_checkable
class CheckEventStore(Protocol):
    async def append(self, check_id: str, type: str, data: Mapping[str, object]) -> StoredEvent:
        """Returns the event as stored, with its sequence number within the check and its
        time."""
        ...

    async def list(self, check_id: str, after_seq: int) -> list[StoredEvent]: ...

    async def count_since(self, user_id: str, type: str, since: datetime) -> tuple[int, EventTimes]:
        """How many events of this type the person logged strictly after the given time, across
        all their checks, deleted ones included, with their times in ascending order."""
        ...

    async def checks_with(self, user_id: str, type: str) -> CheckIds:
        """Ids of the person's checks that hold an event of this type, copied ones included."""
        ...

    async def checks_whose_latest(self, type: str, data: Mapping[str, object]) -> CheckIds:
        """Ids of the checks, of every person, whose latest event of this type has this data."""
        ...
