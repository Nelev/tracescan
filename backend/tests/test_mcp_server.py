from datetime import UTC, datetime, timedelta

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tests.fakes import FixtureTraceReader
from trace_store.const import (
    MAX_ATTR_CHARS_TREE,
    MAX_SUMMARY_CHARS,
    REDACTED,
    TRUNCATION_SUFFIX,
)
from trace_store.mcp_server import build_server
from trace_store.models import SpanNode, TraceSummary
from trace_store.sanitize import sanitize_span, sanitize_summary

T0 = datetime(2026, 11, 5, 9, tzinfo=UTC)
LONG = MAX_ATTR_CHARS_TREE + 1  # over the tree limit, well under the single-span limit


def make_span(**overrides) -> SpanNode:
    fields = dict(
        span_id="s1",
        trace_id="t1",
        name="llm",
        start_time=T0,
        end_time=T0 + timedelta(seconds=1),
    )
    return SpanNode(**{**fields, **overrides})


# A root span with allowlisted keys (long string, number), non-allowlisted keys
# (text and number), events and a child.
SPAN = make_span(
    status_message="m" * LONG,
    attributes={
        "gen_ai.tool.name": "x" * LONG,
        "gen_ai.usage.input_tokens": 7,
        "app.question": "patient text",
        "custom.count": 3,
    },
    events=[
        {
            "name": "e",
            "attributes": {
                "exception.type": "ValidationError",
                "exception.message": "patient text",
            },
        }
    ],
    children=[make_span(span_id="s2", attributes={"gen_ai.tool.name": "y" * LONG})],
)

# A summary whose free-text fields are over the limit.
SUMMARY = TraceSummary(
    trace_id="t1",
    app="medas",
    start_time=T0,
    duration_ms=1.0,
    status="error",
    error_message="e" * (MAX_SUMMARY_CHARS + 1),
    signature="s" * (MAX_SUMMARY_CHARS + 1),
)


class StubReader:
    """Serves SUMMARY as the only failed trace and SPAN as trace t1."""

    async def search_failed_traces(self, query):
        return [SUMMARY]

    async def get_trace_tree(self, trace_id):
        return SPAN if trace_id == "t1" else None

    async def get_span(self, trace_id, span_id):
        return SPAN.model_copy(update={"children": []}) if span_id == "s1" else None


@pytest.fixture
def server():
    return build_server(FixtureTraceReader())


@pytest.fixture
async def client(server):
    async with Client(server) as c:
        yield c


@pytest.fixture
async def stub_client():
    async with Client(build_server(StubReader())) as c:
        yield c


@pytest.mark.anyio
async def test_exposes_exactly_the_three_read_only_tools(client):
    tools = await client.list_tools()
    assert {t.name for t in tools} == {"search_failed_traces", "get_trace_tree", "get_span"}
    assert all(t.annotations.readOnlyHint for t in tools)


@pytest.mark.anyio
async def test_search_failed_traces_returns_summaries(client):
    result = await client.call_tool("search_failed_traces", {"query": {"app": "medas"}})
    ids = [t["trace_id"] for t in result.structured_content["result"]]
    assert ids == ["tr_tool_schema", "tr_retrieval_miss"]


@pytest.mark.anyio
async def test_search_rejects_limit_over_cap(client):
    with pytest.raises(ToolError):
        await client.call_tool("search_failed_traces", {"query": {"app": "medas", "limit": 500}})


@pytest.mark.anyio
async def test_get_trace_tree_nests_children(client):
    tree = await client.call_tool("get_trace_tree", {"trace_id": "tr_retrieval_miss"})
    assert [c["name"] for c in tree.structured_content["children"]] == ["retrieve", "chat gpt-4o"]


@pytest.mark.anyio
async def test_get_span_has_no_children(client):
    one = await client.call_tool(
        "get_span", {"trace_id": "tr_retrieval_miss", "span_id": "sp_rm_retrieve"}
    )
    assert one.structured_content["name"] == "retrieve"
    assert one.structured_content["children"] == []


@pytest.mark.anyio
async def test_unknown_ids_are_tool_errors(client):
    with pytest.raises(ToolError, match="unknown trace_id"):
        await client.call_tool("get_trace_tree", {"trace_id": "nope"})
    with pytest.raises(ToolError, match="unknown span"):
        await client.call_tool("get_span", {"trace_id": "tr_retrieval_miss", "span_id": "nope"})


@pytest.mark.anyio
async def test_fixture_question_is_redacted_but_diagnostic_fields_survive(client):
    tree = await client.call_tool("get_trace_tree", {"trace_id": "tr_retrieval_miss"})
    root = tree.structured_content
    retrieve = root["children"][0]
    assert root["attributes"]["app.question"] == REDACTED
    assert retrieve["attributes"]["retrieval.hits"] == 0
    assert retrieve["status_message"] == "0 chunks above similarity threshold"


def test_sanitize_span_allowlists_truncates_and_recurses():
    sanitized = sanitize_span(SPAN, 100)
    assert sanitized.attributes["gen_ai.tool.name"] == "x" * 100 + TRUNCATION_SUFFIX
    assert sanitized.attributes["gen_ai.usage.input_tokens"] == 7  # allowed by prefix
    assert sanitized.attributes["app.question"] == REDACTED
    assert sanitized.attributes["custom.count"] == REDACTED  # unknown keys fail closed, any type
    assert sanitized.events[0]["attributes"] == {
        "exception.type": "ValidationError",
        "exception.message": REDACTED,
    }
    assert sanitized.children[0].attributes["gen_ai.tool.name"] == "y" * 100 + TRUNCATION_SUFFIX
    assert sanitized.status_message == "m" * 100 + TRUNCATION_SUFFIX


def test_sanitize_summary_truncates_free_text_only():
    sanitized = sanitize_summary(SUMMARY)
    assert sanitized.error_message == "e" * MAX_SUMMARY_CHARS + TRUNCATION_SUFFIX
    assert sanitized.signature == "s" * MAX_SUMMARY_CHARS + TRUNCATION_SUFFIX
    assert sanitized.trace_id == "t1"
    assert (
        sanitize_summary(SUMMARY.model_copy(update={"error_message": None})).error_message is None
    )


@pytest.mark.anyio
async def test_summaries_are_truncated_by_the_tool(stub_client):
    result = await stub_client.call_tool("search_failed_traces", {"query": {"app": "medas"}})
    summary = result.structured_content["result"][0]
    assert summary["error_message"] == "e" * MAX_SUMMARY_CHARS + TRUNCATION_SUFFIX
    assert summary["signature"] == "s" * MAX_SUMMARY_CHARS + TRUNCATION_SUFFIX


@pytest.mark.anyio
async def test_tree_truncates_tighter_than_single_span(stub_client):
    tree = await stub_client.call_tool("get_trace_tree", {"trace_id": "t1"})
    one = await stub_client.call_tool("get_span", {"trace_id": "t1", "span_id": "s1"})
    assert tree.structured_content["attributes"]["gen_ai.tool.name"] == (
        "x" * MAX_ATTR_CHARS_TREE + TRUNCATION_SUFFIX
    )
    assert one.structured_content["attributes"]["gen_ai.tool.name"] == "x" * LONG
    assert one.structured_content["attributes"]["app.question"] == REDACTED
    assert SPAN.attributes["app.question"] == "patient text"  # source object untouched
