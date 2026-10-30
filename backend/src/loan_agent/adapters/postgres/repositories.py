"""Postgres implementations of the persistence ports.

Core building blocks:
- PostgresProfileRepository: one profile row per person, stamped with the repository's clock
- PostgresCheckRepository: check rows, always read through the owning person; deleting one takes
  everything it produced in one transaction
- PostgresOptionRepository, PostgresRecommendationRepository: what a check produced; a check
  keeps one recommendation
- PostgresCheckEventStore: per-check event log; each append locks the check's row, so sequence
  numbers never collide
- Codecs between domain values and JSONB: money as decimal strings, dates as ISO strings

Each call runs in its own session; a write commits before the call returns.
"""

from collections.abc import Callable, Mapping
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import delete, func, select, union_all, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from loan_agent.adapters.postgres.orm import (
    CheckEventRow,
    CheckRow,
    DeletedEventTimeRow,
    OptionRow,
    ProfileRow,
    RecommendationRow,
)
from loan_agent.domain.errors import CheckNotFoundError
from loan_agent.domain.models import (
    Check,
    Goal,
    Option,
    OptionFigures,
    OptionSource,
    Profile,
    Recommendation,
)
from loan_agent.ports.repositories import CheckIds, EventTimes, StoredEvent

Sessions = async_sessionmaker[AsyncSession]


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)


def _profile_data(profile: Profile) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for field in fields(profile):
        value = getattr(profile, field.name)
        data[field.name] = str(value) if isinstance(value, Decimal) else value
    return data


def _profile(data: Mapping[str, Any]) -> Profile:
    values: dict[str, Any] = {}
    for field in fields(Profile):
        value = data[field.name]
        values[field.name] = Decimal(value) if isinstance(value, str) else value
    return Profile(**values)


def _goal_data(goal: Goal) -> dict[str, str]:
    return {"purpose": goal.purpose, "price": str(goal.price)}


def _goal(data: Mapping[str, str]) -> Goal:
    return Goal(data["purpose"], Decimal(data["price"]))


class PostgresProfileRepository:
    def __init__(self, sessions: Sessions, now: Callable[[], datetime]) -> None:
        self._sessions = sessions
        self._now = now

    async def get(self, user_id: str) -> tuple[Profile, datetime | None]:
        async with self._sessions() as session:
            row = await session.get(ProfileRow, user_id)
        if row is None:
            return Profile(), None
        return _profile(row.data), _utc(row.updated_at)

    async def save(self, user_id: str, profile: Profile) -> datetime:
        saved_at = self._now()
        data = _profile_data(profile)
        statement = insert(ProfileRow).values(user_id=user_id, data=data, updated_at=saved_at)
        statement = statement.on_conflict_do_update(
            index_elements=[ProfileRow.user_id], set_={"data": data, "updated_at": saved_at}
        )
        async with self._sessions.begin() as session:
            row = await session.get(ProfileRow, user_id, with_for_update=True)
            if row is not None and _profile(row.data) == profile:
                return _utc(row.updated_at)
            await session.execute(statement)
        return saved_at


class PostgresCheckRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def add(self, check: Check) -> None:
        async with self._sessions.begin() as session:
            session.add(
                CheckRow(
                    id=check.id,
                    user_id=check.user_id,
                    goal=None if check.goal is None else _goal_data(check.goal),
                    profile_snapshot_at=check.profile_snapshot_at,
                    created_at=check.created_at,
                )
            )

    async def get(self, user_id: str, check_id: str) -> Check:
        async with self._sessions() as session:
            row = await session.scalar(
                select(CheckRow).where(CheckRow.id == check_id, CheckRow.user_id == user_id)
            )
        if row is None:
            raise CheckNotFoundError(check_id)
        return _check(row)

    async def list(self, user_id: str) -> list[Check]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(CheckRow)
                .where(CheckRow.user_id == user_id)
                .order_by(CheckRow.created_at.desc())
            )
            return [_check(row) for row in rows]

    async def delete(self, check_id: str, kept_type: str, kept_since: datetime) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(DeletedEventTimeRow).from_select(
                    ["user_id", "type", "created_at"],
                    select(
                        CheckEventRow.user_id, CheckEventRow.type, CheckEventRow.created_at
                    ).where(
                        CheckEventRow.check_id == check_id,
                        CheckEventRow.type == kept_type,
                        CheckEventRow.created_at > kept_since,
                    ),
                )
            )
            await session.execute(
                delete(DeletedEventTimeRow).where(DeletedEventTimeRow.created_at <= kept_since)
            )
            for row in (CheckEventRow, RecommendationRow, OptionRow):
                await session.execute(delete(row).where(row.check_id == check_id))
            await session.execute(delete(CheckRow).where(CheckRow.id == check_id))

    async def set_goal(self, check_id: str, goal: Goal) -> None:
        await self._update(check_id, goal=_goal_data(goal))

    async def snapshot_profile(self, check_id: str, at: datetime) -> None:
        await self._update(check_id, profile_snapshot_at=at)

    async def _update(self, check_id: str, **values: object) -> None:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(CheckRow).where(CheckRow.id == check_id).values(**values)
            )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise CheckNotFoundError(check_id)


def _check(row: CheckRow) -> Check:
    return Check(
        id=row.id,
        user_id=row.user_id,
        created_at=_utc(row.created_at),
        goal=None if row.goal is None else _goal(row.goal),
        profile_snapshot_at=_optional_utc(row.profile_snapshot_at),
    )


class PostgresOptionRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def add(self, option: Option) -> None:
        async with self._sessions.begin() as session:
            session.add(
                OptionRow(
                    id=option.id,
                    check_id=option.check_id,
                    loan=dict(option.loan),
                    source=option.source,
                    lender=option.lender,
                    offer_date=option.offer_date,
                    figures=option.summary.to_json(),
                    created_at=option.created_at,
                )
            )

    async def list(self, check_id: str) -> list[Option]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(OptionRow)
                .where(OptionRow.check_id == check_id)
                .order_by(OptionRow.created_at, OptionRow.id)
            )
            return [_option(row) for row in rows]

    async def get(self, check_id: str, option_id: str) -> Option:
        async with self._sessions() as session:
            row = await session.scalar(
                select(OptionRow).where(OptionRow.check_id == check_id, OptionRow.id == option_id)
            )
        if row is None:
            raise KeyError(option_id)
        return _option(row)


def _option(row: OptionRow) -> Option:
    return Option(
        id=row.id,
        check_id=row.check_id,
        loan=row.loan,
        source=cast(OptionSource, row.source),
        lender=row.lender,
        offer_date=row.offer_date,
        summary=OptionFigures.from_json(row.figures),
        created_at=_utc(row.created_at),
    )


class PostgresRecommendationRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def save(self, recommendation: Recommendation) -> None:
        data = {
            "preferred_option_id": recommendation.preferred_option_id,
            "alternative_option_id": recommendation.alternative_option_id,
            "reasoning": recommendation.reasoning,
            "loan_amount": str(recommendation.loan_amount),
            "payment_ceiling": str(recommendation.payment_ceiling),
            "min_cushion": str(recommendation.min_cushion),
            "cushion_kept": str(recommendation.cushion_kept),
        }
        statement = insert(RecommendationRow).values(
            check_id=recommendation.check_id, data=data, created_at=recommendation.created_at
        )
        statement = statement.on_conflict_do_update(
            index_elements=[RecommendationRow.check_id],
            set_={"data": data, "created_at": recommendation.created_at},
        )
        async with self._sessions.begin() as session:
            await session.execute(statement)

    async def latest(self, check_id: str) -> Recommendation | None:
        async with self._sessions() as session:
            row = await session.get(RecommendationRow, check_id)
        if row is None:
            return None
        data = row.data
        return Recommendation(
            check_id=row.check_id,
            preferred_option_id=data["preferred_option_id"],
            alternative_option_id=data["alternative_option_id"],
            reasoning=data["reasoning"],
            loan_amount=Decimal(data["loan_amount"]),
            payment_ceiling=Decimal(data["payment_ceiling"]),
            min_cushion=Decimal(data["min_cushion"]),
            cushion_kept=Decimal(data["cushion_kept"]),
            created_at=_utc(row.created_at),
        )


class PostgresCheckEventStore:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def append(self, check_id: str, type: str, data: Mapping[str, object]) -> int:
        async with self._sessions.begin() as session:
            owner = await session.scalar(
                select(CheckRow.user_id).where(CheckRow.id == check_id).with_for_update()
            )
            if owner is None:
                raise CheckNotFoundError(check_id)
            last = await session.scalar(
                select(func.coalesce(func.max(CheckEventRow.seq), 0)).where(
                    CheckEventRow.check_id == check_id
                )
            )
            assert last is not None, "coalesce(max(seq), 0) always yields a row"
            seq = last + 1
            session.add(
                CheckEventRow(check_id=check_id, seq=seq, type=type, data=dict(data), user_id=owner)
            )
        return seq

    async def list(self, check_id: str, after_seq: int) -> list[StoredEvent]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(CheckEventRow)
                .where(CheckEventRow.check_id == check_id, CheckEventRow.seq > after_seq)
                .order_by(CheckEventRow.seq)
            )
            return [StoredEvent(r.seq, r.type, r.data, _utc(r.created_at)) for r in rows]

    async def count_since(self, user_id: str, type: str, since: datetime) -> tuple[int, EventTimes]:
        async with self._sessions() as session:
            times = await session.scalars(
                union_all(
                    *(
                        select(row.created_at).where(
                            row.user_id == user_id, row.type == type, row.created_at > since
                        )
                        for row in (CheckEventRow, DeletedEventTimeRow)
                    )
                ).order_by("created_at")
            )
            created = [_utc(t) for t in times]
        return len(created), created

    async def checks_whose_latest(self, type: str, data: Mapping[str, object]) -> CheckIds:
        latest = (
            select(CheckEventRow.check_id, func.max(CheckEventRow.seq).label("seq"))
            .where(CheckEventRow.type == type)
            .group_by(CheckEventRow.check_id)
            .subquery()
        )
        async with self._sessions() as session:
            ids = await session.scalars(
                select(CheckEventRow.check_id)
                .join(
                    latest,
                    (CheckEventRow.check_id == latest.c.check_id)
                    & (CheckEventRow.seq == latest.c.seq),
                )
                .where(CheckEventRow.data == dict(data))
                .order_by(CheckEventRow.check_id)
            )
            return list(ids)
