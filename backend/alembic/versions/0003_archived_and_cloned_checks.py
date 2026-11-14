"""archived and cloned checks

A check is archived once a profile save replaces the figures its recommendation was computed
from. A cloned check copies its source's options under their own ids, so an option's id is
unique within its check, not across all checks; and its copied events never count toward the
person's message cap.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("checks", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("options_pkey", "options", type_="primary")
    op.create_primary_key("options_pkey", "options", ["check_id", "id"])
    op.add_column(
        "check_events",
        sa.Column("copied", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("check_events", "copied")
    op.drop_constraint("options_pkey", "options", type_="primary")
    op.create_primary_key("options_pkey", "options", ["id"])
    op.drop_column("checks", "archived_at")
