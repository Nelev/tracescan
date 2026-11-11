from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from trace_store.models import SpanNode, TraceQuery
from trace_store.reader import build_tree

T0 = datetime(2026, 11, 5, 9, tzinfo=UTC)


def span(span_id: str, parent: str | None, trace_id: str = "t") -> SpanNode:
    return SpanNode(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=parent,
        name=span_id,
        start_time=T0,
        end_time=T0 + timedelta(seconds=1),
    )


def test_query_rejects_limit_over_cap_and_naive_datetimes():
    with pytest.raises(ValidationError):
        TraceQuery(app="medas", limit=500)
    with pytest.raises(ValidationError):
        TraceQuery(app="medas", since=datetime(2026, 11, 5))


def test_build_tree_rejects_two_roots_orphans_and_mixed_traces():
    with pytest.raises(ValueError, match="exactly one root"):
        build_tree([span("a", None), span("b", None)])
    with pytest.raises(ValueError, match="missing parent"):
        build_tree([span("a", None), span("b", "ghost")])
    with pytest.raises(ValueError, match="more than one trace"):
        build_tree([span("a", None), span("b", "a", trace_id="other")])
