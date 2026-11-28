"""recommendation person choice

Code chooses the recommended option by its rule unless the person chose one themselves, so each
stored recommendation records the person's words for that choice, null for the rule's. Every
recommendation stored before was the model's, so each takes null.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""UPDATE recommendations SET data = data || '{"person_choice": null}'""")


def downgrade() -> None:
    op.execute("UPDATE recommendations SET data = data - 'person_choice'")
