"""Integration tests: the client against the real trace server, started as a subprocess."""

from datetime import UTC, datetime

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
    since = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
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
    with pytest.raises(RuntimeError, match="async context manager"):
        await TraceClient().tools()


@pytest.mark.anyio
async def test_tools_are_the_three_read_only_trace_tools(traces):
    names = {tool.name for tool in await traces.tools()}
    assert names == {"search_failed_traces", "get_trace_tree", "get_span"}


@pytest.mark.anyio
async def test_a_tool_call_reaches_the_server(traces):
    tools = {tool.name: tool for tool in await traces.tools()}
    result = await tools["get_trace_tree"].ainvoke({"trace_id": "tr_retrieval_miss"})
    assert "tr_retrieval_miss" in str(result)
    # A call the server rejects comes back as a message, so the agent can adjust instead of the
    # run crashing.
    result = await tools["get_trace_tree"].ainvoke({"trace_id": "no_such_trace"})
    assert "unknown trace_id" in str(result)
