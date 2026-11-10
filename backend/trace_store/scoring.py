"""The scoring job: heuristic checks that say whether a stored trace went wrong.

A trace with no error can still be a failure (a retrieval that found nothing), and an error
can be harmless (a call that was retried and worked). So "failed" is not "has an error span":
each whole trace gets scores, 0.0 for bad and 1.0 for fine, and the reader collects the traces
whose lowest score is low (trace_store/postgres_reader.py).

The checks are plain code over a trace's spans: no model, the same answer every time. A trace
is scored once, right after its root span is stored (api/traces.py); spans that arrive later
do not change its scores. To score traces that have none (stored before this existed, or when
the scoring after a store failed), run from backend/:

    uv run --env-file .env python -m trace_store.scoring
"""

import asyncio
import os
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from db.engine import create_engine
from db.models import Score, Span

Row = Mapping[str, Any]  # one row of `spans`
Scored = tuple[float, str | None]  # the value, and the id of the span it blames, if any

BAD, FINE = 0.0, 1.0
# Errors that are the app working as it should: a tool call that ends in one is not a failure.
EXPECTED_ERRORS = frozenset({"medas.PatientNotFound"})


def _operation(span: Row) -> str | None:
    return span["attributes"].get("gen_ai.operation.name")


def _failed(span: Row) -> bool:
    return span["status"] == "error"


def _exception_type(span: Row) -> str:
    """The exception type a span recorded, on itself or on its first exception event.

    The same places, in the same order, as the reader's SQL (postgres_reader._EXCEPTION_TYPE).
    """
    for attributes in [span["attributes"], *(e.get("attributes") or {} for e in span["events"])]:
        if found := attributes.get("exception.type"):
            return str(found)
    return ""


def origin(error_spans: Sequence[Row]) -> Row:
    """The span a failure started in: an error span with no error span below it.

    An error usually marks every span up to the root, so the deepest one is the cause. With
    several such spans, the one that started first.
    """
    parents = {span["parent_span_id"] for span in error_spans}
    leaves = [span for span in error_spans if span["span_id"] not in parents]
    return min(leaves, key=lambda span: span["start_time"])


def request_failed(spans: Sequence[Row]) -> Scored:
    """The request as a whole failed, blaming the span the failure started in."""
    root = next(span for span in spans if span["parent_span_id"] is None)
    if not _failed(root):
        return FINE, None
    return BAD, origin([span for span in spans if _failed(span)])["span_id"]


def tool_failures(spans: Sequence[Row]) -> dict[str, Scored]:
    """A failed tool call that was not recovered, by what it is: `timeout`, `tool_schema_error`
    or, for anything else that is not an expected error, `tool_error`. The first call of each.

    Recovered: a later call of the same tool in the trace succeeded.
    """
    tools = sorted(
        (span for span in spans if _operation(span) == "execute_tool"),
        key=lambda span: span["start_time"],
    )
    scores: dict[str, Scored] = {}
    for i, call in enumerate(tools):
        recovered = any(not _failed(t) and t["name"] == call["name"] for t in tools[i + 1 :])
        kind = _exception_type(call)
        if not _failed(call) or recovered or kind in EXPECTED_ERRORS:
            continue
        if "Timeout" in kind:
            check = "timeout"
        elif kind.endswith("ValidationError"):
            check = "tool_schema_error"
        else:
            check = "tool_error"
        scores.setdefault(check, (BAD, call["span_id"]))
    return scores


def empty_retrieval(spans: Sequence[Row]) -> Scored | None:
    """A retrieval ran without an error and found nothing. No score when none ran."""
    ran = [span for span in spans if _operation(span) == "retrieval" and not _failed(span)]
    if not ran:
        return None
    empty = [span for span in ran if span["attributes"].get("retrieval.hits") == 0]
    return (BAD, empty[0]["span_id"]) if empty else (FINE, None)


def score_trace(spans: Sequence[Row]) -> dict[str, Scored]:
    """The scores of one whole trace, by check name. Every trace has `request_failed`; every
    bad score blames a span."""
    scores = {"request_failed": request_failed(spans), **tool_failures(spans)}
    if (retrieval := empty_retrieval(spans)) is not None:
        scores["empty_retrieval"] = retrieval
    return scores


async def score_unscored(conn: AsyncConnection, trace_ids: Collection[str] | None = None) -> int:
    """Score the whole traces (the root span is stored) that have no score yet; how many.

    Among `trace_ids` when given (what the collector just stored), else in the whole store.
    """
    whole = select(Span.trace_id).where(
        Span.parent_span_id.is_(None), ~exists().where(Score.trace_id == Span.trace_id)
    )
    if trace_ids is not None:
        whole = whole.where(Span.trace_id.in_(trace_ids))
    rows = await conn.execute(select(*Span.__table__.columns).where(Span.trace_id.in_(whole)))
    traces: dict[str, list[Row]] = {}
    for span in rows.mappings():
        traces.setdefault(span["trace_id"], []).append(dict(span))
    scores = [
        {"trace_id": trace_id, "evaluator": name, "value": value, "span_id": span_id}
        for trace_id, spans in traces.items()
        for name, (value, span_id) in score_trace(spans).items()
    ]
    if scores:
        await conn.execute(insert(Score).on_conflict_do_nothing(), scores)
    return len(traces)


async def _score_stored(database_url: str) -> int:
    engine = create_engine(database_url)
    try:
        async with engine.begin() as conn:
            return await score_unscored(conn)
    finally:
        await engine.dispose()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("set DATABASE_URL (the application's role: it writes to scores)")
    print(f"{asyncio.run(_score_stored(database_url))} traces scored")


if __name__ == "__main__":
    main()
