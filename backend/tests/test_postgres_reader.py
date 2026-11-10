"""The Postgres trace reader, over the spans the collector stores. Needs TEST_DATABASE_URL."""

import pytest
from sqlalchemy import text

from agent.mcp_client import TraceClient
from api.traces import decode
from api.traces import store_spans as store
from tests.test_traces_api import CHILD_ID, ROOT_ID, START, TRACE_ID, export, post
from trace_store.models import FailedTraceQuery

MEDAS = FailedTraceQuery(app="medas")


@pytest.mark.anyio
async def test_a_posted_trace_comes_back_through_the_trace_server(
    collector, spans_engine, postgres_url
):
    # The whole path: collector -> spans -> Postgres reader -> MCP server -> client.
    assert (await post(collector, export())).status_code == 200

    async with TraceClient(postgres_url) as traces:
        (summary,) = await traces.search_failed_traces(MEDAS)
        tree = await traces.get_trace_tree(summary.trace_id)

    assert summary.trace_id == TRACE_ID.hex()
    assert (summary.status, summary.start_time, summary.duration_ms) == ("error", START, 2000.0)
    assert (summary.failing_span_id, summary.failing_span_name) == (CHILD_ID.hex(), "retrieval")
    assert summary.error_message == "no documents"
    assert summary.signature == "retrieval EmptyRetrieval"
    assert (tree.span_id, tree.name) == (ROOT_ID.hex(), "request")
    assert [child.span_id for child in tree.children] == [CHILD_ID.hex()]


@pytest.mark.anyio
async def test_only_failed_traces_of_an_allowed_app_are_served(spans_engine, reader):
    root, child = decode(export())
    healthy = {**root, "trace_id": "a" * 32}
    other_app = [{**span, "trace_id": "b" * 32, "app": "someone-else"} for span in (root, child)]
    await store(spans_engine, [root, child, healthy, *other_app])

    assert [s.trace_id for s in await reader.search_failed_traces(MEDAS)] == [TRACE_ID.hex()]
    assert await reader.search_failed_traces(FailedTraceQuery(app="someone-else")) == []
    assert await reader.get_trace_tree("b" * 32) is None
    assert await reader.get_span("b" * 32, ROOT_ID.hex()) is None
    span = await reader.get_span(TRACE_ID.hex(), CHILD_ID.hex())
    assert span is not None and span.status_message == "no documents"


@pytest.mark.anyio
async def test_a_trace_whose_root_has_not_arrived_is_not_served(spans_engine, reader):
    _, child = decode(export())
    await store(spans_engine, [child])

    assert await reader.search_failed_traces(MEDAS) == []
    assert await reader.get_trace_tree(TRACE_ID.hex()) is None


@pytest.mark.anyio
async def test_the_reader_cannot_write(read_only):
    with pytest.raises(Exception, match="read-only"):
        async with read_only.begin() as conn:
            await conn.execute(text("TRUNCATE spans"))
