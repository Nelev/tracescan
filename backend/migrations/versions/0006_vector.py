"""vector: the pgvector extension, for the healthy-span store (runs/healthy.py)

Only the extension: langchain-postgres's PGVector creates its own two tables
(langchain_pg_collection, langchain_pg_embedding) on first use, and migrations/env.py keeps
autogenerate away from them.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS langchain_pg_embedding")
    op.execute("DROP TABLE IF EXISTS langchain_pg_collection")
    op.execute("DROP EXTENSION IF EXISTS vector")
