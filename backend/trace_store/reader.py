"""
Trace reader: the single seam between the MCP tools and the trace data.

The MCP server only calls the three TraceReader methods, so the fixture reader
here and the Postgres reader (later) are interchangeable.
"""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from trace_store.models import FailedTraceQuery, SpanNode, TraceSummary

DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "medas_traces.json"


class TraceReader(Protocol):
    """Read-only access to traces. Returns None when an id is unknown."""

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]: ...

    async def get_trace_tree(self, trace_id: str) -> SpanNode | None: ...

    async def get_span(self, trace_id: str, span_id: str) -> SpanNode | None: ...


def build_tree(spans: list[SpanNode]) -> SpanNode:
    """Nest flat span rows under their parents. Shared by every reader implementation."""
    if len({s.trace_id for s in spans}) > 1:
        raise ValueError("spans belong to more than one trace")
    ids = {s.span_id for s in spans}
    roots = [s for s in spans if s.parent_span_id is None]
    orphans = [s.span_id for s in spans if s.parent_span_id and s.parent_span_id not in ids]
    if orphans:
        raise ValueError(f"spans with a missing parent: {orphans}")
    if len(roots) != 1:
        raise ValueError(f"expected exactly one root span, found {len(roots)}")

    nodes = {s.span_id: s.model_copy(update={"children": []}) for s in spans}
    for span in sorted(spans, key=lambda s: s.start_time):
        if span.parent_span_id:
            nodes[span.parent_span_id].children.append(nodes[span.span_id])
    return nodes[roots[0].span_id]


def _is_failed(summary: TraceSummary, max_score: float) -> bool:
    """Its lowest score is low. A summary with no score counts a status of error as 0."""
    score = summary.min_score
    if score is None:
        score = 0.0 if summary.status == "error" else 1.0
    return score <= max_score


class _FixtureTrace(BaseModel):
    summary: TraceSummary
    spans: list[SpanNode]


class _FixtureFile(BaseModel):
    traces: list[_FixtureTrace]


class FixtureTraceReader:
    """Serves the synthetic fixture. Trusts the stored summaries."""

    def __init__(self, path: Path = DEFAULT_FIXTURE) -> None:
        self._summaries: dict[str, TraceSummary] = {}
        self._trees: dict[str, SpanNode] = {}
        self._spans: dict[str, dict[str, SpanNode]] = {}
        for trace in _FixtureFile.model_validate_json(path.read_bytes()).traces:
            trace_id = trace.summary.trace_id
            tree = build_tree(trace.spans)  # fails at load time on a broken fixture
            if tree.trace_id != trace_id:
                raise ValueError(f"spans do not belong to trace {trace_id}")
            self._summaries[trace_id] = trace.summary
            self._trees[trace_id] = tree
            self._spans[trace_id] = {s.span_id: s for s in trace.spans}

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        matches = [
            s
            for s in self._summaries.values()
            if s.app == query.app
            and (query.since is None or s.start_time >= query.since)
            and (query.until is None or s.start_time < query.until)
            and _is_failed(s, query.max_score)
        ]
        matches.sort(key=lambda s: s.start_time, reverse=True)
        return matches[: query.limit]

    async def get_trace_tree(self, trace_id: str) -> SpanNode | None:
        return self._trees.get(trace_id)

    async def get_span(self, trace_id: str, span_id: str) -> SpanNode | None:
        span = self._spans.get(trace_id, {}).get(span_id)
        return span.model_copy(update={"children": []}) if span else None
