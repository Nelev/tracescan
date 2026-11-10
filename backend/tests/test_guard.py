import logging

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tests.fakes import FixtureTraceReader
from trace_store.mcp_server import build_server

SEARCH = {"query": {"app": "medas"}}
OTHER_APP = {"query": {"app": "other"}}


@pytest.fixture
async def client():
    async with Client(build_server(FixtureTraceReader())) as c:
        yield c


@pytest.mark.anyio
async def test_allowed_app_and_ids_pass(client):
    await client.call_tool("search_failed_traces", SEARCH)
    await client.call_tool("get_trace_tree", {"trace_id": "tr_retrieval_miss"})
    await client.call_tool(
        "get_span", {"trace_id": "tr_retrieval_miss", "span_id": "sp_rm_retrieve"}
    )


@pytest.mark.anyio
async def test_other_app_is_rejected(client):
    with pytest.raises(ToolError, match="app not allowed"):
        await client.call_tool("search_failed_traces", OTHER_APP)


@pytest.mark.anyio
async def test_custom_allowed_apps():
    async with Client(build_server(FixtureTraceReader(), allowed_apps={"other"})) as c:
        with pytest.raises(ToolError, match="app not allowed"):
            await c.call_tool("search_failed_traces", SEARCH)


@pytest.mark.anyio
@pytest.mark.parametrize("bad_id", ["../x", "a" * 65, "", "has space", "a\n"])
async def test_malformed_trace_id_is_rejected(client, bad_id):
    with pytest.raises(ToolError, match="pattern"):
        await client.call_tool("get_trace_tree", {"trace_id": bad_id})


@pytest.mark.anyio
async def test_malformed_span_id_is_rejected(client):
    with pytest.raises(ToolError, match="pattern"):
        await client.call_tool("get_span", {"trace_id": "tr_retrieval_miss", "span_id": "../x"})


@pytest.mark.anyio
async def test_id_pattern_is_in_the_tool_schema(client):
    tools = {t.name: t for t in await client.list_tools()}
    props = tools["get_span"].inputSchema["properties"]
    assert props["trace_id"]["pattern"] == props["span_id"]["pattern"]


@pytest.mark.anyio
async def test_call_budget_counts_allowed_and_rejected_calls():
    async with Client(build_server(FixtureTraceReader(), max_calls=2)) as c:
        await c.call_tool("search_failed_traces", SEARCH)
        with pytest.raises(ToolError, match="app not allowed"):
            await c.call_tool("search_failed_traces", OTHER_APP)
        with pytest.raises(ToolError, match="call budget exhausted"):
            await c.call_tool("search_failed_traces", SEARCH)


@pytest.mark.anyio
async def test_audit_log_has_outcomes_but_not_arguments(caplog):
    caplog.set_level(logging.INFO, logger="trace_store.guard")
    async with Client(build_server(FixtureTraceReader(), max_calls=2)) as c:
        await c.call_tool("search_failed_traces", SEARCH)
        with pytest.raises(ToolError):
            await c.call_tool("get_trace_tree", {"trace_id": "patient secret"})
        with pytest.raises(ToolError):
            await c.call_tool("get_trace_tree", {"trace_id": "tr_retrieval_miss"})

    # Only the guard's own records: FastMCP logs the rejected id itself (see guard.py).
    log = "\n".join(r.getMessage() for r in caplog.records if r.name == "trace_store.guard")
    assert "tool call ok: tool=search_failed_traces" in log
    assert "tool call error: tool=get_trace_tree" in log
    assert "tool call denied: tool=get_trace_tree" in log
    assert "patient secret" not in log
    assert "medas" not in log
