"""Postgres implementations of the persistence ports.

Core building blocks:
- PostgresCheckRepository: check rows with their loan, term, ceiling and finances, always read
  through the owning person; deleting or cloning one takes everything it produced in one
  transaction
- PostgresOptionRepository, PostgresRecommendationRepository: what a check produced; a check
  keeps one recommendation
- PostgresCheckEventStore: per-check event log; each append locks the check's row, so sequence
  numbers never collide
- Codecs between domain values and JSONB: money as decimal strings, dates as ISO strings

Each call runs in its own session; a write commits before the call returns.
"""

from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import delete, false, func, literal, select, union_all, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from loan_agent.adapters.postgres.orm import (
    CheckEventRow,
    CheckRow,
    DeletedEventTimeRow,
    OptionRow,
    RecommendationRow,
)
from loan_agent.domain.errors import CheckNotFoundError
from loan_agent.domain.models import (
    CeilingSource,
    Check,
    Finances,
    LoanRequest,
    Option,
    OptionFigures,
    OptionSource,
    Recommendation,
)
from loan_agent.ports.repositories import CheckIds, EventTimes, StoredEvent

Sessions = async_sessionmaker[AsyncSession]


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)


def _text_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal_or_none(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _loan_data(loan: LoanRequest) -> dict[str, str | None]:
    return {"purpose": loan.purpose, "amount": str(loan.amount)}


def _loan(data: Mapping[str, str | None]) -> LoanRequest:
    amount = data["amount"]
    assert amount is not None, "a stored loan always has an amount"
    return LoanRequest(data["purpose"], Decimal(amount))


def _finances_data(finances: Finances) -> dict[str, str | None]:
    return {
        "net_fixed_income": _text_or_none(finances.net_fixed_income),
        "fixed_expenses": _text_or_none(finances.fixed_expenses),
    }


def _finances(data: Mapping[str, str | None]) -> Finances:
    """An empty object reads as no figure told; any other object names both figures."""
    if not data:
        return Finances()
    return Finances(
        net_fixed_income=_decimal_or_none(data["net_fixed_income"]),
        fixed_expenses=_decimal_or_none(data["fixed_expenses"]),
    )


class PostgresCheckRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def add(self, check: Check) -> None:
        async with self._sessions.begin() as session:
            session.add(_check_row(check))

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
                        CheckEventRow.copied == false(),
                    ),
                )
            )
            await session.execute(
                delete(DeletedEventTimeRow).where(DeletedEventTimeRow.created_at <= kept_since)
            )
            for row in (CheckEventRow, RecommendationRow, OptionRow):
                await session.execute(delete(row).where(row.check_id == check_id))
            await session.execute(delete(CheckRow).where(CheckRow.id == check_id))

    async def set_loan(self, check_id: str, loan: LoanRequest) -> None:
        await self._update(check_id, loan=_loan_data(loan))

    async def set_term(self, check_id: str, term_months: int) -> None:
        await self._update(check_id, term_months=term_months)

    async def set_ceiling(self, check_id: str, ceiling: Decimal, source: CeilingSource) -> None:
        await self._update(check_id, payment_ceiling=ceiling, ceiling_source=source)

    async def set_finances(self, check_id: str, finances: Finances) -> None:
        await self._update(check_id, finances=_finances_data(finances))

    async def latest_finances(self, user_id: str, other_than: str) -> Finances | None:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(CheckRow.finances)
                .where(CheckRow.user_id == user_id, CheckRow.id != other_than)
                .order_by(CheckRow.created_at.desc())
            )
            for data in rows:
                finances = _finances(data)
                if not finances.missing():
                    return finances
        return None

    async def archive(self, check_id: str, at: datetime) -> None:
        await self._update(check_id, archived_at=at)

    async def restore(self, check_id: str) -> None:
        await self._update(check_id, archived_at=None)

    async def clone(self, source_id: str, clone: Check, left_out: Collection[str]) -> None:
        kept = (
            select(
                CheckEventRow,
                func.row_number().over(order_by=CheckEventRow.seq).label("copy_seq"),
            )
            .where(CheckEventRow.check_id == source_id, CheckEventRow.type.not_in(left_out))
            .subquery()
        )
        async with self._sessions.begin() as session:
            session.add(_check_row(clone))
            await session.flush()
            await session.execute(
                insert(OptionRow).from_select(
                    [
                        "check_id",
                        "id",
                        "loan",
                        "source",
                        "lender",
                        "offer_date",
                        "max_term_months",
                        "figures",
                        "created_at",
                    ],
                    select(
                        literal(clone.id),
                        OptionRow.id,
                        OptionRow.loan,
                        OptionRow.source,
                        OptionRow.lender,
                        OptionRow.offer_date,
                        OptionRow.max_term_months,
                        OptionRow.figures,
                        OptionRow.created_at,
                    ).where(OptionRow.check_id == source_id),
                )
            )
            await session.execute(
                insert(RecommendationRow).from_select(
                    ["check_id", "data", "created_at"],
                    select(
                        literal(clone.id), RecommendationRow.data, RecommendationRow.created_at
                    ).where(RecommendationRow.check_id == source_id),
                )
            )
            await session.execute(
                insert(CheckEventRow).from_select(
                    ["check_id", "seq", "type", "data", "user_id", "created_at", "copied"],
                    select(
                        literal(clone.id),
                        kept.c.copy_seq,
                        kept.c.type,
                        kept.c.data,
                        kept.c.user_id,
                        kept.c.created_at,
                        literal(True),
                    ),
                )
            )

    async def _update(self, check_id: str, **values: object) -> None:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(CheckRow).where(CheckRow.id == check_id).values(**values)
            )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise CheckNotFoundError(check_id)


def _check_row(check: Check) -> CheckRow:
    return CheckRow(
        id=check.id,
        user_id=check.user_id,
        loan=None if check.loan is None else _loan_data(check.loan),
        term_months=check.term_months,
        payment_ceiling=check.payment_ceiling,
        ceiling_source=check.ceiling_source,
        finances=_finances_data(check.finances),
        created_at=check.created_at,
        archived_at=check.archived_at,
    )


def _check(row: CheckRow) -> Check:
    return Check(
        id=row.id,
        user_id=row.user_id,
        created_at=_utc(row.created_at),
        loan=None if row.loan is None else _loan(row.loan),
        term_months=row.term_months,
        payment_ceiling=row.payment_ceiling,
        ceiling_source=cast(CeilingSource | None, row.ceiling_source),
        finances=_finances(row.finances),
        archived_at=_optional_utc(row.archived_at),
    )


class PostgresOptionRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def add(self, option: Option) -> None:
        async with self._sessions.begin() as session:
            session.add(_option_row(option))

    async def replace(self, option: Option) -> None:
        async with self._sessions.begin() as session:
            existing = await session.get(OptionRow, (option.check_id, option.id))
            if existing is None:
                raise KeyError(option.id)
            await session.merge(_option_row(option))

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


def _option_row(option: Option) -> OptionRow:
    return OptionRow(
        id=option.id,
        check_id=option.check_id,
        loan=dict(option.loan),
        source=option.source,
        lender=option.lender,
        offer_date=option.offer_date,
        max_term_months=option.max_term_months,
        figures=option.summary.to_json(),
        created_at=option.created_at,
    )


def _option(row: OptionRow) -> Option:
    return Option(
        id=row.id,
        check_id=row.check_id,
        loan=row.loan,
        source=cast(OptionSource, row.source),
        lender=row.lender,
        offer_date=row.offer_date,
        max_term_months=row.max_term_months,
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
            "payment_ceiling": _text_or_none(recommendation.payment_ceiling),
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
            payment_ceiling=_decimal_or_none(data["payment_ceiling"]),
            created_at=_utc(row.created_at),
        )


class PostgresCheckEventStore:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def append(self, check_id: str, type: str, data: Mapping[str, object]) -> StoredEvent:
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
            row = CheckEventRow(
                check_id=check_id, seq=last + 1, type=type, data=dict(data), user_id=owner
            )
            session.add(row)
            # The database stamps the time, so the row is read back before the session closes.
            await session.flush()
            await session.refresh(row)
            return StoredEvent(row.seq, row.type, row.data, _utc(row.created_at))

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
                    select(CheckEventRow.created_at).where(
                        CheckEventRow.user_id == user_id,
                        CheckEventRow.type == type,
                        CheckEventRow.created_at > since,
                        CheckEventRow.copied == false(),
                    ),
                    select(DeletedEventTimeRow.created_at).where(
                        DeletedEventTimeRow.user_id == user_id,
                        DeletedEventTimeRow.type == type,
                        DeletedEventTimeRow.created_at > since,
                    ),
                ).order_by("created_at")
            )
            created = [_utc(t) for t in times]
        return len(created), created

    async def checks_with(self, user_id: str, type: str) -> CheckIds:
        async with self._sessions() as session:
            ids = await session.scalars(
                select(CheckEventRow.check_id)
                .where(CheckEventRow.user_id == user_id, CheckEventRow.type == type)
                .distinct()
                .order_by(CheckEventRow.check_id)
            )
            return list(ids)

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
