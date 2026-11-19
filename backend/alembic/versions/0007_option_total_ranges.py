"""option total ranges

Each option's stored figures gain the lowest and highest total repaid across the historical
windows, which the model reads to answer "the best and the worst case". The engine reported them
in every option.saved event, so each option takes them from its latest one.

Revision ID: 0007
Revises: 0006
"""

from alembic import op
from sqlalchemy import text

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# The range in each option's latest option.saved event; null for a payment that never moves.
_LATEST_RANGE = """
    SELECT DISTINCT ON (e.check_id, e.data->>'option_id')
        e.check_id, e.data->>'option_id' AS option_id,
        e.data->'result'->'tracks'->0->'total_paid_range' AS total_range
    FROM check_events e
    WHERE e.type = 'option.saved'
    ORDER BY e.check_id, e.data->>'option_id', e.seq DESC
"""


def upgrade() -> None:
    connection = op.get_bind()
    missing = connection.execute(
        text(
            f"""
            SELECT o.check_id, o.id FROM options o
            LEFT JOIN ({_LATEST_RANGE}) r ON r.check_id = o.check_id AND r.option_id = o.id
            WHERE o.figures->>'worst_peak_payment' IS NOT NULL
              AND (r.total_range IS NULL OR jsonb_typeof(r.total_range) <> 'object')
            """
        )
    ).all()
    if missing:
        names = ", ".join(f"{check_id}/{option_id}" for check_id, option_id in missing)
        raise RuntimeError(
            f"options whose payment moves have no saved range of totals: {names}; reset their "
            "checks first (scripts/tools/sql-helper.sh --reset <account-id>)"
        )
    connection.execute(
        text(
            f"""
            UPDATE options o SET figures = o.figures || jsonb_build_object(
                'total_paid_low', r.total_range->'low',
                'total_paid_high', r.total_range->'high')
            FROM ({_LATEST_RANGE}) r
            WHERE r.check_id = o.check_id AND r.option_id = o.id
              AND o.figures->>'worst_peak_payment' IS NOT NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE options SET figures = figures || '{"total_paid_low": null,
                "total_paid_high": null}'::jsonb
            WHERE figures->>'worst_peak_payment' IS NULL
            """
        )
    )


def downgrade() -> None:
    op.execute("UPDATE options SET figures = figures - 'total_paid_low' - 'total_paid_high'")
