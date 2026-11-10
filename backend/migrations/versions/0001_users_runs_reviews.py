"""users, runs and reviews

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("target_app", sa.String(), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True)),
        sa.Column("until", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("failed_traces", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clusters", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proposals", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "status IN ('in_progress', 'review_required', 'reviewing', 'completed', 'failed', "
            "'aborted')",
            name="runs_status_known",
        ),
    )
    op.create_index("runs_created_at", "runs", [sa.text("created_at DESC")])
    op.create_table(
        "reviews",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("cluster_id", sa.String(), primary_key=True),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("decision IN ('approve', 'reject')", name="reviews_decision_known"),
    )


def downgrade() -> None:
    op.drop_table("reviews")
    op.drop_index("runs_created_at", table_name="runs")
    op.drop_table("runs")
    op.drop_table("users")
