"""The application's tables: the runs people start, and what they decide.

They sit in the same database as the graph checkpoints (DATABASE_URL). `runs` and `reviews` hold
ids, names, counts and decisions only: no issue text and no span content. A person is a name the
client sent (there is no login), stored as it is in the row that names them. The checkpoint
stays the record of a run's state and proposals; `runs` is the index and the lifecycle around it.
`spans` is the exception: it is the trace store, and holds what the collector received;
`scores` is what the heuristic checks say about each of its traces (ids and numbers only).

Change a table here, then write a migration: `uv run alembic revision --autogenerate -m "..."`.
"""

from datetime import datetime
from typing import Any, Literal, get_args
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agent.schemas import Decision
from trace_store.models import SpanStatus

# A new status or decision also needs a migration: the check constraints list them.
RunStatus = Literal["in_progress", "review_required", "completed", "failed", "aborted"]
RUN_STATUSES = get_args(RunStatus)
DECISIONS = get_args(Decision)
SPAN_STATUSES = get_args(SpanStatus)
NAME_MAX = 80  # the width of a stored name; a longer one is cut (auth.current_user)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


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
    # Null only for rows from before names were required.
    started_by: Mapped[str | None] = mapped_column(String(NAME_MAX))
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
    reviewer: Mapped[str] = mapped_column(String(NAME_MAX))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Span(Base):
    """One span as the collector received it (api/traces.py).

    Unlike the other tables this one holds span content (attributes, events, status messages),
    which for Medas can be clinical text. A trace is the spans that share a `trace_id`.
    """

    __tablename__ = "spans"
    __table_args__ = (
        CheckConstraint(_one_of("status", SPAN_STATUSES), name="spans_status_known"),
        Index("spans_app_start_time", "app", text("start_time DESC")),
    )

    trace_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    span_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(16))
    app: Mapped[str]  # the resource's service.name
    name: Mapped[str]
    kind: Mapped[str] = mapped_column(String(20))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10))
    status_message: Mapped[str | None]
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)


class Score(Base):
    """What a check says about one stored trace; read by the trace browser.

    The heuristic scoring job that wrote these rows is removed; nothing writes them for now.

    0.0 is bad and 1.0 is fine. A trace counts as failed when its lowest score is low. `span_id`
    is the span the check blames, when it blames one. Ids and numbers only, no span content.
    """

    __tablename__ = "scores"

    trace_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    evaluator: Mapped[str] = mapped_column(primary_key=True)  # the check's name
    value: Mapped[float] = mapped_column(Float)
    span_id: Mapped[str | None] = mapped_column(String(16))
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
