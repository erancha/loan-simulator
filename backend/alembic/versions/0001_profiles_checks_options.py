"""profiles, checks, options, recommendations and check events

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "checks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("goal", postgresql.JSONB(), nullable=True),
        sa.Column("profile_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_checks_user_id", "checks", ["user_id"])
    op.create_table(
        "options",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("check_id", sa.Text(), sa.ForeignKey("checks.id"), nullable=False),
        sa.Column("loan", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("lender", sa.Text(), nullable=True),
        sa.Column("offer_date", sa.Date(), nullable=True),
        sa.Column("figures", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_options_check_id", "options", ["check_id"])
    op.create_table(
        "recommendations",
        sa.Column("check_id", sa.Text(), sa.ForeignKey("checks.id"), primary_key=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "check_events",
        sa.Column("check_id", sa.Text(), sa.ForeignKey("checks.id"), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "check_events_user_type_time", "check_events", ["user_id", "type", "created_at"]
    )


def downgrade() -> None:
    """Drops the agent's tables; the checkpointer's tables, which env.py creates outside any
    revision, stay."""
    for table in ("check_events", "recommendations", "options", "checks", "profiles"):
        op.drop_table(table)
