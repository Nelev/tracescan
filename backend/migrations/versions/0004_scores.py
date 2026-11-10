"""scores: what the heuristic checks say about each stored trace

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scores",
        sa.Column("trace_id", sa.String(32), primary_key=True),
        sa.Column("evaluator", sa.String(), primary_key=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("span_id", sa.String(16)),
        sa.Column(
            "scored_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("scores")
