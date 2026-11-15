"""Tables of the loan agent: checks with their options, recommendation and event log.

Every row belongs to a Google account id; options and recommendations reach it through their
check, while events also carry it themselves. Money inside JSONB columns is a decimal string
and dates are ISO strings."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CheckRow(Base):
    __tablename__ = "checks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, index=True)
    loan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """The requested loan: purpose (nullable) and amount as a decimal string."""
    term_months: Mapped[int | None] = mapped_column(Integer)
    payment_ceiling: Mapped[Decimal | None] = mapped_column(Numeric)
    ceiling_source: Mapped[str | None] = mapped_column(Text)
    finances: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    """The finances told so far, money as decimal strings; a figure not yet told is null."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OptionRow(Base):
    """An option's id is unique within its check: a cloned check keeps its source's option ids,
    which its conversation names."""

    __tablename__ = "options"

    check_id: Mapped[str] = mapped_column(ForeignKey("checks.id"), primary_key=True, index=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    loan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(Text)
    lender: Mapped[str | None] = mapped_column(Text)
    offer_date: Mapped[date | None] = mapped_column(Date)
    max_term_months: Mapped[int | None] = mapped_column(Integer)
    figures: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecommendationRow(Base):
    __tablename__ = "recommendations"

    check_id: Mapped[str] = mapped_column(ForeignKey("checks.id"), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CheckEventRow(Base):
    __tablename__ = "check_events"
    __table_args__ = (Index("check_events_user_type_time", "user_id", "type", "created_at"),)

    check_id: Mapped[str] = mapped_column(ForeignKey("checks.id"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    user_id: Mapped[str] = mapped_column(Text)
    """The check's owner, repeated so the per-person message count needs no join."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    copied: Mapped[bool] = mapped_column(Boolean, server_default=false())
    """Copied from the check a clone was made of; the person's message count leaves it out."""


class DeletedEventTimeRow(Base):
    """When a deleted check's event happened, with no content, so a count over time still sees it
    until it falls out of the counted window."""

    __tablename__ = "deleted_event_times"
    __table_args__ = (Index("deleted_event_times_user_type_time", "user_id", "type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
