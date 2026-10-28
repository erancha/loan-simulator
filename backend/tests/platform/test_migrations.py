"""The migration run alone prepares every table the app needs, the checkpointer's included; the
schema it builds matches the ORM, and its downgrade removes the agent's tables."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from langgraph.checkpoint.postgres.base import MIGRATIONS
from psycopg import AsyncConnection
from sqlalchemy import create_engine

from loan_agent.adapters.postgres.orm import Base
from loan_agent.platform.checkpointer import libpq_dsn

BACKEND_DIR = Path(__file__).resolve().parents[2]
AGENT_TABLES = ("profiles", "checks", "options", "recommendations", "check_events")


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
