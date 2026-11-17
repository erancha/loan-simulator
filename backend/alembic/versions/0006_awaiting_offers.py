"""awaiting offers

A lender's offer whose words leave its type open waits, with the loans it may mean, until the
person tells which one the lender meant.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "awaiting_offers",
        sa.Column("check_id", sa.Text(), sa.ForeignKey("checks.id"), primary_key=True),
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("lender", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("awaiting_offers")
