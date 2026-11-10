"""The trace reader over Postgres: the `spans` table the collector writes (api/traces.py).

The simplest version. There is no traces or scores table, so a trace is the spans that share
a trace_id, and a failed trace is one with a root span and at least one span of status error.
Give it TRACE_DATABASE_URL; the session is opened read-only, whatever the role may do.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from sqlalchemy import exists, func, literal_column, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import aliased

from db.engine import sqlalchemy_url
from db.models import Span
from trace_store.const import ALLOWED_APPS
from trace_store.models import FailedTraceQuery, SpanNode, TraceSummary
from trace_store.reader import build_tree

# The columns of a SpanNode (everything but `app`).
_NODE_COLUMNS = [c for c in Span.__table__.columns if c.name != "app"]
# The exception type a span recorded, on itself or on its first exception event. Read in SQL,
# so a search fetches no attributes or events (they can be large, and are span content).
_EXCEPTION_TYPE = func.coalesce(
    Span.attributes["exception.type"].astext,
    func.jsonb_path_query_first(
        Span.events, literal_column("""'$[*].attributes."exception.type"'"""), type_=JSONB
    ).op("#>>")(literal_column("'{}'")),
).label("exception_type")


def read_only_engine(database_url: str) -> AsyncEngine:
    """An engine whose every transaction is read-only."""
    return create_async_engine(
        sqlalchemy_url(database_url),
        connect_args={"options": "-c default_transaction_read_only=on"},
    )


def origin(error_spans: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The span a failure started in: an error span with no error span below it.

    An error usually marks every span up to the root, so the deepest one is the cause. With
    several such spans, the one that started first.
    """
    parents = {span["parent_span_id"] for span in error_spans}
    leaves = [span for span in error_spans if span["span_id"] not in parents]
    return min(leaves, key=lambda span: span["start_time"])


class PostgresTraceReader:
    """Serves the traces of `apps` only, on every method."""

    def __init__(self, engine: AsyncEngine, apps: Collection[str] = ALLOWED_APPS) -> None:
        self._engine = engine
        self._apps = list(apps)

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        # max_score is not used: there are no scores yet, so only an error status is a failure.
        if query.app not in self._apps:
            return []
        error = aliased(Span)
        roots = select(Span.trace_id, Span.start_time, Span.end_time).where(
            Span.parent_span_id.is_(None),
            Span.app == query.app,
            exists().where(error.trace_id == Span.trace_id, error.status == "error"),
        )
        if query.since is not None:
            roots = roots.where(Span.start_time >= query.since)
        if query.until is not None:
            roots = roots.where(Span.start_time < query.until)
        roots = roots.order_by(Span.start_time.desc(), Span.trace_id).limit(query.limit)

        async with self._engine.connect() as conn:
            traces = (await conn.execute(roots)).mappings().all()
            if not traces:
                return []
            errors = await conn.execute(
                select(
                    Span.trace_id,
                    Span.span_id,
                    Span.parent_span_id,
                    Span.name,
                    Span.start_time,
                    Span.status_message,
                    _EXCEPTION_TYPE,
                ).where(
                    Span.trace_id.in_([trace["trace_id"] for trace in traces]),
                    Span.status == "error",
                )
            )
            error_spans: dict[str, list[Mapping[str, Any]]] = {}
            for span in errors.mappings():
                error_spans.setdefault(span["trace_id"], []).append(span)

        summaries = []
        for trace in traces:
            failing = origin(error_spans[trace["trace_id"]])
            summaries.append(
                TraceSummary(
                    trace_id=trace["trace_id"],
                    app=query.app,
                    start_time=trace["start_time"],
                    duration_ms=(trace["end_time"] - trace["start_time"]).total_seconds() * 1000,
                    status="error",
                    error_message=failing["status_message"],
                    failing_span_id=failing["span_id"],
                    failing_span_name=failing["name"],
                    # Names only: no message and no attribute value, so no span content.
                    signature=" ".join(filter(None, [failing["name"], failing["exception_type"]])),
                )
            )
        return summaries

    async def _spans(self, *where) -> list[SpanNode]:
        statement = select(*_NODE_COLUMNS).where(Span.app.in_(self._apps), *where)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(statement)).mappings().all()
        return [SpanNode.model_validate(dict(row)) for row in rows]

    async def get_trace_tree(self, trace_id: str) -> SpanNode | None:
        spans = await self._spans(Span.trace_id == trace_id)
        try:
            return build_tree(spans)
        except ValueError:
            # Unknown, or not whole (no root yet, a missing parent): there is no tree to show.
            return None

    async def get_span(self, trace_id: str, span_id: str) -> SpanNode | None:
        spans = await self._spans(Span.trace_id == trace_id, Span.span_id == span_id)
        return spans[0] if spans else None
