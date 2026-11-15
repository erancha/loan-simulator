"""offer max term

A real offer that leaves its term open keeps the longest term its lender allows, so the offer
can be priced again at the check's term whenever that changes.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("options", sa.Column("max_term_months", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("options", "max_term_months")
