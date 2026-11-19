"""The migration run alone prepares every table the app needs, the checkpointer's included; the
schema it builds matches the ORM, and its downgrade removes the agent's tables."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from langgraph.checkpoint.postgres.base import MIGRATIONS
from psycopg import AsyncConnection
from sqlalchemy import create_engine, text

from loan_agent.adapters.postgres.orm import Base
from loan_agent.platform.checkpointer import libpq_dsn

BACKEND_DIR = Path(__file__).resolve().parents[2]
AGENT_TABLES = (
    "checks",
    "options",
    "recommendations",
    "check_events",
    "deleted_event_times",
    "awaiting_offers",
)


async def _scalar(pg_url: str, sql: str) -> object:
    async with await AsyncConnection.connect(libpq_dsn(pg_url)) as conn:
        row = await (await conn.execute(sql)).fetchone()
    assert row is not None
    return row[0]


async def test_migrations_create_tables_and_checkpoint_tables(pg_url: str) -> None:
    for table in AGENT_TABLES:
        assert await _scalar(pg_url, f"SELECT to_regclass('{table}')") == table
    version = await _scalar(pg_url, "SELECT max(v) FROM checkpoint_migrations")
    assert version == len(MIGRATIONS) - 1


def _agent_objects(name: str | None, type_: str, parent_names: object) -> bool:
    """Leaves out the checkpointer's tables and Alembic's own, which the ORM does not declare."""
    return type_ != "table" or name in Base.metadata.tables


def test_the_migrated_schema_matches_the_orm(pg_url: str) -> None:
    engine = create_engine(pg_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"include_name": _agent_objects, "compare_type": True}
            )
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert differences == []


async def test_downgrade_removes_the_agent_tables_and_upgrade_restores_them(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

    command.downgrade(config, "base")
    for table in AGENT_TABLES:
        assert await _scalar(pg_url, f"SELECT to_regclass('{table}')") is None

    command.upgrade(config, "head")
    for table in AGENT_TABLES:
        assert await _scalar(pg_url, f"SELECT to_regclass('{table}')") == table


async def test_migration_0004_refuses_a_database_with_checks(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(config, "0003")
    engine = create_engine(pg_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO checks (id, user_id, created_at) VALUES ('c-old', 'p', :at)"),
                {"at": datetime(2026, 10, 1, tzinfo=UTC)},
            )

        with pytest.raises(RuntimeError, match="sql-helper.sh --reset-all"):
            command.upgrade(config, "head")
        assert await _scalar(pg_url, "SELECT to_regclass('profiles')") == "profiles"

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM checks"))
    finally:
        engine.dispose()
    command.upgrade(config, "head")
    assert await _scalar(pg_url, "SELECT to_regclass('profiles')") is None


def _option_and_event(
    connection: object, option_id: str, worst: str | None, saved: list[object]
) -> None:
    figures = {"worst_peak_payment": worst, "total_paid": "100000"}
    connection.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO options (check_id, id, loan, source, figures, created_at) "
            "VALUES ('c1', :id, '{}'::jsonb, 'offer', CAST(:figures AS jsonb), :at)"
        ),
        {"id": option_id, "figures": json.dumps(figures), "at": datetime(2026, 10, 1, tzinfo=UTC)},
    )
    for seq, total_range in saved:
        result = {"tracks": [{"total_paid_range": total_range}]}
        connection.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO check_events (check_id, seq, type, data, user_id) "
                "VALUES ('c1', :seq, 'option.saved', CAST(:data AS jsonb), 'p')"
            ),
            {"seq": seq, "data": json.dumps({"option_id": option_id, "result": result})},
        )


async def test_migration_0007_copies_each_options_range_from_its_latest_saved_event(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(config, "0006")
    engine = create_engine(pg_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO checks (id, user_id, created_at) VALUES ('c1', 'p', :at)"),
                {"at": datetime(2026, 10, 1, tzinfo=UTC)},
            )
            stale = {"low": "1", "high": "2"}
            latest = {"low": "99000.00", "high": "104000.00"}
            _option_and_event(connection, "moving", "2000", [(1, stale), (2, latest)])
            _option_and_event(connection, "steady", None, [(3, None)])
        command.upgrade(config, "head")
        with engine.begin() as connection:
            rows = dict(connection.execute(text("SELECT id, figures FROM options")).all())
        assert (rows["moving"]["total_paid_low"], rows["moving"]["total_paid_high"]) == (
            "99000.00",
            "104000.00",
        )
        assert (rows["steady"]["total_paid_low"], rows["steady"]["total_paid_high"]) == (None, None)
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM check_events"))
            connection.execute(text("DELETE FROM options"))
            connection.execute(text("DELETE FROM checks"))
        engine.dispose()


async def test_migration_0007_refuses_a_moving_option_without_a_saved_range(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(config, "0006")
    engine = create_engine(pg_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO checks (id, user_id, created_at) VALUES ('c1', 'p', :at)"),
                {"at": datetime(2026, 10, 1, tzinfo=UTC)},
            )
            _option_and_event(connection, "orphan", "2000", [])

        with pytest.raises(RuntimeError, match="orphan"):
            command.upgrade(config, "head")
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM check_events"))
            connection.execute(text("DELETE FROM options"))
            connection.execute(text("DELETE FROM checks"))
        engine.dispose()
    command.upgrade(config, "head")
