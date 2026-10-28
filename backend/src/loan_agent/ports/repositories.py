"""Persistence ports: what the application needs to keep and read back.

- ProfileRepository: the person's finances, one row per person
- CheckRepository, OptionRepository, RecommendationRepository: a check and what it produced
- CheckEventStore: the per-check event log, also the source of the per-person message count
- StoredEvent: one logged event as read back

Every method that takes a user id answers only for that person's rows.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from loan_agent.domain.models import Check, Goal, Option, Profile, Recommendation

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
class ProfileRepository(Protocol):
    async def get(self, user_id: str) -> tuple[Profile, datetime | None]:
        """The stored profile and when it was last saved; an empty profile and None when the
        person has none."""
        ...

    async def save(self, user_id: str, profile: Profile) -> datetime:
        """Replaces the stored profile; returns the save time, which snapshot_profile records on a
        check to tell later saves apart."""
        ...


@runtime_checkable
class CheckRepository(Protocol):
    async def add(self, check: Check) -> None: ...

    async def get(self, user_id: str, check_id: str) -> Check:
        """Raises CheckNotFoundError for an unknown id and for another person's check."""
        ...

    async def list(self, user_id: str) -> list[Check]:
        """Newest first."""
        ...

    async def set_goal(self, check_id: str, goal: Goal) -> None: ...

    async def snapshot_profile(self, check_id: str, at: datetime) -> None:
        """Records the profile version the check's recommendation was computed from. A check is
        stale when the profile was saved after this time."""
        ...


@runtime_checkable
class OptionRepository(Protocol):
    async def add(self, option: Option) -> None: ...

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
    async def append(self, check_id: str, type: str, data: Mapping[str, object]) -> int:
        """Returns the event's sequence number within the check."""
        ...

    async def list(self, check_id: str, after_seq: int) -> list[StoredEvent]: ...

    async def count_since(self, user_id: str, type: str, since: datetime) -> tuple[int, EventTimes]:
        """How many events of this type the person logged strictly after the given time, across
        all their checks, with their times in ascending order."""
        ...

    async def checks_ending_with(self, type: str, data: Mapping[str, object]) -> CheckIds:
        """Ids of the checks, of every person, whose latest event has this type and data."""
        ...
