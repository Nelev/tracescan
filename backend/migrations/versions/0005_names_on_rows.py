"""names on rows: runs.started_by and reviews.reviewer hold the name; users is dropped

A name is whatever the client sent (there is no login), so a table of them added a join and an
upsert and identified nobody. The names are copied onto the rows before the table goes.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NAME = sa.String(80)


def upgrade() -> None:
    op.add_column("runs", sa.Column("started_by_name", NAME))
    op.execute(
        "UPDATE runs SET started_by_name = users.name FROM users WHERE runs.started_by = users.id"
    )
    op.drop_column("runs", "started_by")  # drops its foreign key with it
    op.alter_column("runs", "started_by_name", new_column_name="started_by")

    op.add_column("reviews", sa.Column("reviewer", NAME))
    op.execute(
        "UPDATE reviews SET reviewer = users.name FROM users WHERE reviews.reviewer_id = users.id"
    )
    op.alter_column("reviews", "reviewer", nullable=False)
    op.drop_column("reviews", "reviewer_id")

    op.drop_table("users")


def downgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", NAME, nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        "INSERT INTO users (id, name) SELECT gen_random_uuid(), name FROM ("
        " SELECT started_by AS name FROM runs WHERE started_by IS NOT NULL"
        " UNION SELECT reviewer FROM reviews) AS names"
    )

    op.alter_column("runs", "started_by", new_column_name="started_by_name")
    op.add_column("runs", sa.Column("started_by", sa.Uuid(), sa.ForeignKey("users.id")))
    op.execute(
        "UPDATE runs SET started_by = users.id FROM users WHERE runs.started_by_name = users.name"
    )
    op.drop_column("runs", "started_by_name")

    op.add_column("reviews", sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("users.id")))
    op.execute(
        "UPDATE reviews SET reviewer_id = users.id FROM users WHERE reviews.reviewer = users.name"
    )
    op.alter_column("reviews", "reviewer_id", nullable=False)
    op.drop_column("reviews", "reviewer")
