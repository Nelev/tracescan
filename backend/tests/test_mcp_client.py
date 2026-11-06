"""Integration tests: the client against the real trace server, started as a subprocess."""

from datetime import datetime, timezone

import pytest

from agent.mcp_client import TraceClient
from trace_store.models import FailedTraceQuery, TraceSummary


@pytest.mark.anyio
async def test_search_returns_typed_summaries(traces):
    found = await traces.search_failed_traces(FailedTraceQuery(app="medas"))
    assert all(isinstance(t, TraceSummary) for t in found)
    assert [t.trace_id for t in found] == ["tr_tool_schema", "tr_retrieval_miss"]


@pytest.mark.anyio
async def test_query_datetimes_reach_the_server(traces):
    since = datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc)
    found = await traces.search_failed_traces(FailedTraceQuery(app="medas", since=since))
    assert [t.trace_id for t in found] == ["tr_tool_schema"]


@pytest.mark.anyio
async def test_one_session_serves_several_calls(traces):
    query = FailedTraceQuery(app="medas")
    first = await traces.search_failed_traces(query)
    for _ in range(3):
        assert await traces.search_failed_traces(query) == first


@pytest.mark.anyio
async def test_using_the_client_outside_its_context_raises():
    with pytest.raises(RuntimeError, match="async context manager"):
        await TraceClient().search_failed_traces(FailedTraceQuery(app="medas"))
