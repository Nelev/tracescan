"""
Trace reader: the single seam between the MCP tools and the trace data.

The MCP server only calls the three TraceReader methods. The one implementation is the
Postgres reader (trace_store/postgres_reader.py); tests have their own small ones.
"""

from typing import Protocol

from trace_store.models import SpanNode, TraceQuery, TraceSummary


class TraceReader(Protocol):
    """Read-only access to traces. Returns None when an id is unknown."""

    async def search_traces(self, query: TraceQuery) -> list[TraceSummary]: ...

    async def get_trace_tree(self, trace_id: str) -> SpanNode | None: ...

    async def get_span(self, trace_id: str, span_id: str) -> SpanNode | None: ...


def build_tree(spans: list[SpanNode]) -> SpanNode:
    """Nest flat span rows under their parents."""
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
