"""The trace reader over Postgres: the `spans` table the collector writes (api/traces.py).

There is no traces table: a trace is the spans that share a trace_id, and a trace is served
once its root span is stored. search_traces reads no scores: which traces failed is the agent's
trace judge's call. The trace browser's reads (list_traces, get_trace_detail) show what `scores`
holds: a trace is failed there when its lowest score is at most FAILED_MAX_SCORE, and its failing
span is the one that score blames. The rows are the trace judge's verdicts, saved after each run
(runs/scores.py), so a trace no run has judged yet reads as unscored.
Give it TRACE_DATABASE_URL; the session is opened read-only, whatever the role may do.
"""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import ColumnElement, RowMapping, ScalarSelect, and_, func, literal_column, select
from sqlalchemy.dialects.postgresql import JSONB, distinct_on
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.orm import aliased

from db.engine import sqlalchemy_url
from db.models import Score, Span
from trace_store.const import ALLOWED_APPS, FAILED_MAX_SCORE
from trace_store.models import (
    SpanNode,
    TraceDetail,
    TraceQuery,
    TraceRow,
    TraceScore,
    TraceSummary,
    is_failed,
)
from trace_store.reader import build_tree

# The columns of a SpanNode (everything but `app`).
_NODE_COLUMNS = [c for c in Span.__table__.columns if c.name != "app"]
# What kind of error a span recorded: its `error.type` attribute, else the type of its first
# exception event. Read in SQL, so a search fetches no attributes or events (they can be large,
# and are span content).
_EXCEPTION_TYPE = func.coalesce(
    Span.attributes["error.type"].astext,
    Span.attributes["exception.type"].astext,
    func.jsonb_path_query_first(
        Span.events, literal_column("""'$[*].attributes."exception.type"'"""), type_=JSONB
    ).op("#>>")(literal_column("'{}'")),
).label("exception_type")


async def _blamed(
    conn: AsyncConnection, trace_ids: list[str], max_score: float
) -> dict[str, RowMapping]:
    """Per trace, the span its lowest score blames (of several, the first check by name).

    Only traces with a score at most `max_score` appear; every such score blames a span.
    """
    rows = await conn.execute(
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
        .where(Score.trace_id.in_(trace_ids), Score.value <= max_score)
        .order_by(Score.trace_id, Score.value, Score.evaluator)
    )
    return {row["trace_id"]: row for row in rows.mappings()}


def read_only_engine(database_url: str) -> AsyncEngine:
    """An engine whose every transaction is read-only."""
    return create_async_engine(
        sqlalchemy_url(database_url),
        connect_args={"options": "-c default_transaction_read_only=on"},
    )


def _listed_roots(
    app: str, since: datetime | None, until: datetime | None, failed_only: bool
) -> tuple[type[Span], ScalarSelect[float], list[ColumnElement[bool]]]:
    """The root spans a trace list holds: their alias, each one's lowest score, and the filters.

    Shared by the list and its count, so the two can never disagree about which traces are in.
    """
    root = aliased(Span, name="root")
    # Per root, probing the scores' key: no aggregate over the whole table.
    lowest = select(func.min(Score.value)).where(Score.trace_id == root.trace_id).scalar_subquery()
    listed: list[ColumnElement[bool]] = [root.parent_span_id.is_(None), root.app == app]
    if failed_only:
        listed.append(lowest <= FAILED_MAX_SCORE)
    if since is not None:
        listed.append(root.start_time >= since)
    if until is not None:
        listed.append(root.start_time < until)
    return root, lowest, listed


class PostgresTraceReader:
    """Serves the traces of `apps` only, on every method."""

    def __init__(self, engine: AsyncEngine, apps: Collection[str] = ALLOWED_APPS) -> None:
        self._engine = engine
        self._apps = list(apps)

    async def search_traces(self, query: TraceQuery) -> list[TraceSummary]:
        """Every trace of the app with a root span in the window, newest first, failed or not.

        Reads the root spans only, and no scores, attributes or events: the summary holds ids,
        timing, the root's status and its name as the signature. Which traces failed is the
        agent's call (agent/judge.py), from the tree it fetches.
        """
        if query.app not in self._apps:
            return []
        roots = select(Span.trace_id, Span.name, Span.start_time, Span.end_time, Span.status).where(
            Span.parent_span_id.is_(None), Span.app == query.app
        )
        if query.since is not None:
            roots = roots.where(Span.start_time >= query.since)
        if query.until is not None:
            roots = roots.where(Span.start_time < query.until)
        roots = roots.order_by(Span.start_time.desc(), Span.trace_id).limit(query.limit)

        async with self._engine.connect() as conn:
            rows = (await conn.execute(roots)).mappings().all()
        return [
            TraceSummary(
                trace_id=row["trace_id"],
                app=query.app,
                start_time=row["start_time"],
                duration_ms=(row["end_time"] - row["start_time"]).total_seconds() * 1000,
                status=row["status"],
                signature=row["name"],
            )
            for row in rows
        ]

    async def list_traces(
        self,
        app: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        failed_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TraceRow]:
        """The newest whole-rooted traces of `app`, failed or not, unscored ones included.

        A trace whose root span has not arrived is not listed. `offset` skips that many of the
        newest, so the list can be read page by page. Reads no attributes or events.
        """
        if app not in self._apps:
            return []
        root, lowest, listed = _listed_roots(app, since, until, failed_only)
        span_count = (
            select(func.count())
            .select_from(Span)
            .where(Span.trace_id == root.trace_id)
            .scalar_subquery()
        )
        roots = select(
            root.trace_id,
            root.start_time,
            root.end_time,
            root.status,
            lowest.label("low"),
            span_count.label("spans"),
        ).where(*listed)
        roots = roots.order_by(root.start_time.desc(), root.trace_id).limit(limit).offset(offset)

        async with self._engine.connect() as conn:
            traces = (await conn.execute(roots)).mappings().all()
            failed_ids = [t["trace_id"] for t in traces if is_failed(t["low"])]
            blamed = await _blamed(conn, failed_ids, FAILED_MAX_SCORE) if failed_ids else {}

        rows = []
        for trace in traces:
            failing = blamed.get(trace["trace_id"])  # every bad score blames a span
            rows.append(
                TraceRow(
                    trace_id=trace["trace_id"],
                    app=app,
                    start_time=trace["start_time"],
                    duration_ms=(trace["end_time"] - trace["start_time"]).total_seconds() * 1000,
                    status=trace["status"],
                    spans=trace["spans"],
                    min_score=trace["low"],
                    failed=is_failed(trace["low"]),
                    failing_span_id=failing["span_id"] if failing else None,
                    failing_span_name=failing["name"] if failing else None,
                    failing_check=failing["evaluator"] if failing else None,
                    error_type=failing["exception_type"] if failing else None,
                )
            )
        return rows

    async def count_traces(
        self,
        app: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        failed_only: bool = False,
    ) -> int:
        """How many traces `list_traces` would list with the same filters, over all its pages."""
        if app not in self._apps:
            return 0
        root, _, listed = _listed_roots(app, since, until, failed_only)
        async with self._engine.connect() as conn:
            counted = select(func.count()).select_from(root).where(*listed)
            return (await conn.execute(counted)).scalar_one()

    async def get_trace_detail(self, trace_id: str) -> TraceDetail | None:
        """One trace's tree (raw: the caller sanitizes it) and its scores, on one connection.

        None when the trace is unknown, of another app, or not whole; its scores are then not read.
        """
        async with self._engine.connect() as conn:
            tree = await self._tree(conn, trace_id)
            if tree is None:
                return None
            # The tree has a root, so its app is there to read.
            app = (
                await conn.execute(
                    select(Span.app).where(Span.trace_id == trace_id, Span.parent_span_id.is_(None))
                )
            ).scalar_one()
            rows = await conn.execute(
                select(Score.evaluator, Score.value, Score.span_id)
                .where(Score.trace_id == trace_id)
                .order_by(Score.evaluator)
            )
        scores = [TraceScore(**row, failed=is_failed(row["value"])) for row in rows.mappings()]
        low = min((s.value for s in scores), default=None)
        return TraceDetail(
            trace_id=trace_id,
            app=app,
            tree=tree,
            scores=scores,
            min_score=low,
            failed=is_failed(low),
        )

    async def _spans(self, conn: AsyncConnection, *where) -> list[SpanNode]:
        statement = select(*_NODE_COLUMNS).where(Span.app.in_(self._apps), *where)
        rows = (await conn.execute(statement)).mappings().all()
        return [SpanNode.model_validate(dict(row)) for row in rows]

    async def _tree(self, conn: AsyncConnection, trace_id: str) -> SpanNode | None:
        try:
            return build_tree(await self._spans(conn, Span.trace_id == trace_id))
        except ValueError:
            # Unknown, or not whole (no root yet, a missing parent): there is no tree to show.
            return None

    async def get_trace_tree(self, trace_id: str) -> SpanNode | None:
        async with self._engine.connect() as conn:
            return await self._tree(conn, trace_id)

    async def get_span(self, trace_id: str, span_id: str) -> SpanNode | None:
        async with self._engine.connect() as conn:
            spans = await self._spans(conn, Span.trace_id == trace_id, Span.span_id == span_id)
        return spans[0] if spans else None
