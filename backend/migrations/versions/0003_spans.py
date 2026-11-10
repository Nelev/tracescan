"""spans: the trace store the collector writes

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spans",
        sa.Column("trace_id", sa.String(32), primary_key=True),
        sa.Column("span_id", sa.String(16), primary_key=True),
        sa.Column("parent_span_id", sa.String(16)),
        sa.Column("app", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("status_message", sa.String()),
        sa.Column("attributes", JSONB(), nullable=False),
        sa.Column("events", JSONB(), nullable=False),
        sa.CheckConstraint("status IN ('unset', 'ok', 'error')", name="spans_status_known"),
    )
    op.create_index("spans_app_start_time", "spans", ["app", sa.text("start_time DESC")])


def downgrade() -> None:
    op.drop_table("spans")
