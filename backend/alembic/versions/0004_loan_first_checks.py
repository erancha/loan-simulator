"""loan-first checks

A check holds the requested loan, its term, the payment ceiling and the person's finances,
which replace the goal, the profile snapshot time and the per-person profiles table. The old
rows cannot be migrated, so the migration refuses a database that still holds checks.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    has_checks = op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM checks)"))
    if has_checks:
        raise RuntimeError(
            "The checks table still holds checks, which this migration deletes rather than "
            "migrates; empty the database first: ./scripts/tools/sql-helper.sh --reset-all"
        )
    op.drop_column("checks", "goal")
    op.drop_column("checks", "profile_snapshot_at")
    op.add_column("checks", sa.Column("loan", postgresql.JSONB(), nullable=True))
    op.add_column("checks", sa.Column("term_months", sa.Integer(), nullable=True))
    op.add_column("checks", sa.Column("payment_ceiling", sa.Numeric(), nullable=True))
    op.add_column("checks", sa.Column("ceiling_source", sa.Text(), nullable=True))
    op.add_column(
        "checks",
        sa.Column(
            "finances",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.drop_table("profiles")


def downgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("finances", "ceiling_source", "payment_ceiling", "term_months", "loan"):
        op.drop_column("checks", column)
    op.add_column("checks", sa.Column("goal", postgresql.JSONB(), nullable=True))
    op.add_column(
        "checks", sa.Column("profile_snapshot_at", sa.DateTime(timezone=True), nullable=True)
    )
