from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from trace_store.models import FailedTraceQuery, SpanNode
from trace_store.reader import FixtureTraceReader, build_tree

T0 = datetime(2026, 11, 5, 9, tzinfo=UTC)


@pytest.fixture
def reader() -> FixtureTraceReader:
    return FixtureTraceReader()


def span(span_id: str, parent: str | None, trace_id: str = "t") -> SpanNode:
    return SpanNode(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=parent,
        name=span_id,
        start_time=T0,
        end_time=T0 + timedelta(seconds=1),
    )


@pytest.mark.anyio
async def test_search_returns_failed_traces_newest_first(reader):
    found = await reader.search_failed_traces(FailedTraceQuery(app="medas"))
    assert [t.trace_id for t in found] == ["tr_tool_schema", "tr_retrieval_miss"]


@pytest.mark.anyio
async def test_search_time_window_drops_traces(reader):
    query = FailedTraceQuery(app="medas", since=datetime(2026, 11, 5, 9, 30, tzinfo=UTC))
    found = await reader.search_failed_traces(query)
    assert [t.trace_id for t in found] == ["tr_tool_schema"]


@pytest.mark.anyio
async def test_search_limit_and_unknown_app(reader):
    one = await reader.search_failed_traces(FailedTraceQuery(app="medas", limit=1))
    assert len(one) == 1
    assert await reader.search_failed_traces(FailedTraceQuery(app="other")) == []


def test_query_rejects_limit_over_cap_and_naive_datetimes():
    with pytest.raises(ValidationError):
        FailedTraceQuery(app="medas", limit=500)
    with pytest.raises(ValidationError):
        FailedTraceQuery(app="medas", since=datetime(2026, 11, 5))


@pytest.mark.anyio
async def test_get_trace_tree_nests_children_in_time_order(reader):
    root = await reader.get_trace_tree("tr_retrieval_miss")
    assert root.name == "medas.request"
    assert [c.name for c in root.children] == ["retrieve", "chat gpt-4o"]


@pytest.mark.anyio
async def test_get_span_has_no_children(reader):
    found = await reader.get_span("tr_retrieval_miss", "sp_rm_root")
    assert found.name == "medas.request"
    assert found.children == []


@pytest.mark.anyio
async def test_unknown_ids_return_none(reader):
    assert await reader.get_trace_tree("nope") is None
    assert await reader.get_span("tr_retrieval_miss", "nope") is None
    assert await reader.get_span("nope", "sp_rm_root") is None


def test_build_tree_rejects_two_roots_orphans_and_mixed_traces():
    with pytest.raises(ValueError, match="exactly one root"):
        build_tree([span("a", None), span("b", None)])
    with pytest.raises(ValueError, match="missing parent"):
        build_tree([span("a", None), span("b", "ghost")])
    with pytest.raises(ValueError, match="more than one trace"):
        build_tree([span("a", None), span("b", "a", trace_id="other")])
