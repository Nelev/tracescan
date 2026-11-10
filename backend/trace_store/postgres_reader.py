"""The trace reader over Postgres: the `spans` table the collector writes (api/traces.py).

There is no traces table: a trace is the spans that share a trace_id. A failed trace is one
with a root span whose lowest score (trace_store/scoring.py) is at most the query's max_score.
An error span alone does not make a trace failed, and a trace with no scores yet is not served.
The failing span of a trace is the one its lowest score blames.
Give it TRACE_DATABASE_URL; the session is opened read-only, whatever the role may do.
"""

from collections.abc import Collection

from sqlalchemy import and_, func, literal_column, select
from sqlalchemy.dialects.postgresql import JSONB, distinct_on
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from db.engine import sqlalchemy_url
from db.models import Score, Span
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


class PostgresTraceReader:
    """Serves the traces of `apps` only, on every method."""

    def __init__(self, engine: AsyncEngine, apps: Collection[str] = ALLOWED_APPS) -> None:
        self._engine = engine
        self._apps = list(apps)

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        if query.app not in self._apps:
            return []
        # Root spans, each with its trace's lowest score: Postgres lets the other root columns
        # be selected because the grouping is by the table's primary key.
        lowest = func.min(Score.value)
        roots = (
            select(Span.trace_id, Span.start_time, Span.end_time, Span.status, lowest.label("low"))
            .join(Score, Score.trace_id == Span.trace_id)
            .where(Span.parent_span_id.is_(None), Span.app == query.app)
            .group_by(Span.trace_id, Span.span_id)
            .having(lowest <= query.max_score)
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
            # Per trace, the span its lowest score blames (of several, the first check by name).
            blamed_spans = await conn.execute(
                select(
                    Score.trace_id,
                    Score.evaluator,
                    Span.span_id,
                    Span.name,
                    Span.status_message,
                    _EXCEPTION_TYPE,
                )
                .ext(distinct_on(Score.trace_id))
                .join(Span, and_(Span.trace_id == Score.trace_id, Span.span_id == Score.span_id))
                .where(
                    Score.trace_id.in_([trace["trace_id"] for trace in traces]),
                    Score.value <= query.max_score,
                )
                .order_by(Score.trace_id, Score.value, Score.evaluator)
            )
            blamed = {span["trace_id"]: span for span in blamed_spans.mappings()}

        summaries = []
        for trace in traces:
            failing = blamed[trace["trace_id"]]  # every low score blames a span
            summaries.append(
                TraceSummary(
                    trace_id=trace["trace_id"],
                    app=query.app,
                    start_time=trace["start_time"],
                    duration_ms=(trace["end_time"] - trace["start_time"]).total_seconds() * 1000,
                    status=trace["status"],
                    error_message=failing["status_message"],
                    failing_span_id=failing["span_id"],
                    failing_span_name=failing["name"],
                    min_score=trace["low"],
                    # Names only (the span, then its exception type or, without one, the check
                    # that scored it low): no message and no attribute value.
                    signature=f"{failing['name']} {failing['exception_type'] or failing['evaluator']}",
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
