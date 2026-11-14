"""Saves the person's profile and archives the checks whose recommendation the save leaves behind.

A recommendation is computed from the profile as saved at one time; once a save changes a figure,
the check's conversation and card describe figures the person no longer has. Such a check is
archived rather than left to read as current: it keeps its log, takes no more messages, and its
log ends with a check.archived event that holds the whole replaced profile and what changed.

- save_profile: merge, save, archive the checks recommended from the replaced profile
- manual_archive_data: the same event's data for a check the person archived themselves
- SavedProfile: the saved profile and the ids of the checks archived
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime

from loan_agent.domain.models import Profile
from loan_agent.ports.events import CHECK_ARCHIVED, EventSink
from loan_agent.ports.repositories import CheckRepository, ProfileRepository


@dataclass(frozen=True)
class SavedProfile:
    profile: Profile
    archived: list[str]
    """Ids of the checks this save archived."""


async def save_profile(
    user_id: str,
    update: Mapping[str, object],
    profiles: ProfileRepository,
    checks: CheckRepository,
    sink: EventSink,
    clock: Callable[[], datetime],
) -> SavedProfile:
    """Raises ProfileError, naming the field, before anything is saved. A check recommended from
    an older version is already stale and stays as it is: its log cannot say which figures it
    was computed from."""
    previous, previous_at = await profiles.get(user_id)
    profile = previous.merged(update)
    await profiles.save(user_id, profile)
    if profile == previous:
        return SavedProfile(profile, [])
    archived = []
    for check in await checks.list(user_id):
        recommended = check.profile_snapshot_at is not None
        if recommended and check.archived_at is None and check.profile_snapshot_at == previous_at:
            now = clock()
            await checks.archive(check.id, now)
            await sink.emit(check.id, CHECK_ARCHIVED, _archive_data(previous, profile, now))
            archived.append(check.id)
    return SavedProfile(profile, archived)


def manual_archive_data(at: datetime) -> dict[str, object]:
    """The check.archived data of a check the person archived themselves: no profile was
    replaced."""
    return {"previous_profile": None, "changes": [], "archived_at": at.isoformat()}


def _archive_data(previous: Profile, profile: Profile, at: datetime) -> dict[str, object]:
    before, after = asdict(previous), asdict(profile)
    return manual_archive_data(at) | {
        "previous_profile": {name: _text(value) for name, value in before.items()},
        "changes": [
            {"field": name, "from": _text(before[name]), "to": _text(after[name])}
            for name in before
            if before[name] != after[name]
        ],
    }


def _text(value: object) -> str | None:
    return None if value is None else str(value)
