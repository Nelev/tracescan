"""The application's tables: who uses TraceScan, the runs they start, and what they decide.

They sit in the same database as the graph checkpoints (DATABASE_URL) and hold ids, counts and
decisions only: no issue text and no span content. The checkpoint stays the record of a run's
state and proposals; `runs` is the index and the lifecycle around it.

Change a table here, then write a migration: `uv run alembic revision --autogenerate -m "..."`.
"""

from datetime import datetime
from typing import Literal, get_args
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agent.schemas import Decision

# A new status or decision also needs a migration: the check constraints list them.
RunStatus = Literal["in_progress", "review_required", "completed", "failed", "aborted"]
RUN_STATUSES = get_args(RunStatus)
DECISIONS = get_args(Decision)
NAME_MAX = 80  # the width of users.name, and so the longest name the API accepts


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class User(Base):
    """A person, recorded by name only. There is no login: the name is whatever the client says."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(NAME_MAX), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(_one_of("status", RUN_STATUSES), name="runs_status_known"),
        Index("runs_created_at", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)  # the graph's thread_id
    target_app: Mapped[str]
    since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    # Null for a run that was first recorded at its review (started before this table existed).
    started_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_traces: Mapped[int] = mapped_column(server_default="0")
    clusters: Mapped[int] = mapped_column(server_default="0")
    proposals: Mapped[int] = mapped_column(server_default="0")


class Review(Base):
    """One decision on one proposal of a run."""

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint(_one_of("decision", DECISIONS), name="reviews_decision_known"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    cluster_id: Mapped[str] = mapped_column(primary_key=True)
    decision: Mapped[str] = mapped_column(String(10))
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
