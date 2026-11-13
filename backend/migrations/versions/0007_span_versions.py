"""span versions: spans.app_version and spans.schema_url

The resource's service.version and the export's telemetry schema URL, kept by the collector so
the healthy-span store can match a failed step only with healthy calls of the same app version
and the same telemetry schema. Nullable: older spans and apps that send neither have none.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spans", sa.Column("app_version", sa.String(128)))
    op.add_column("spans", sa.Column("schema_url", sa.String(256)))


def downgrade() -> None:
    op.drop_column("spans", "schema_url")
    op.drop_column("spans", "app_version")
