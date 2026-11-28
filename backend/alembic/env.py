"""Alembic environment: runs the revisions against the database DATABASE_URL names, with the
ORM tables as the target metadata. An online run then creates the LangGraph checkpointer's
tables, or brings them to the installed library's version, which no revision does."""

import os

from alembic import context
from sqlalchemy import create_engine

from loan_agent.adapters.postgres.orm import Base
from loan_agent.platform.checkpointer import libpq_dsn, setup_checkpoint_tables

target_metadata = Base.metadata
url = os.environ["DATABASE_URL"]


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
    setup_checkpoint_tables(libpq_dsn(url))


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
