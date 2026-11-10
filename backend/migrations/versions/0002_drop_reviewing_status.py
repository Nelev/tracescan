"""drop the reviewing status

A review now holds its run with a row lock for as long as it is applied, so no status has to say
"being reviewed": a run a dead process left in `reviewing` waits for review again.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

WITHOUT = "status IN ('in_progress', 'review_required', 'completed', 'failed', 'aborted')"
WITH = "status IN ('in_progress', 'review_required', 'reviewing', 'completed', 'failed', 'aborted')"


def upgrade() -> None:
    op.execute("UPDATE runs SET status = 'review_required' WHERE status = 'reviewing'")
    op.drop_constraint("runs_status_known", "runs", type_="check")
    op.create_check_constraint("runs_status_known", "runs", WITHOUT)


def downgrade() -> None:
    op.drop_constraint("runs_status_known", "runs", type_="check")
    op.create_check_constraint("runs_status_known", "runs", WITH)
