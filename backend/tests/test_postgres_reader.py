"""The Postgres trace reader, over the spans the collector stores. Needs TEST_DATABASE_URL."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from agent.mcp_client import TraceClient
from api.traces import decode
from api.traces import store_spans as store
from tests.test_traces_api import CHILD_ID, ROOT_ID, START, TRACE_ID, export, post
from trace_store.models import FailedTraceQuery, TraceQuery

MEDAS = FailedTraceQuery(app="medas")


def later_copy(span: dict, trace_id: str, **overrides) -> dict:
    """The span as the root of another trace, an hour later."""
    hour = timedelta(hours=1)
    return {
        **span,
        "trace_id": trace_id,
        "start_time": span["start_time"] + hour,
        "end_time": span["end_time"] + hour,
        **overrides,
    }


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
    # The request went on after the failed tool call: the root is not an error, the score is low.
    assert (summary.status, summary.start_time, summary.duration_ms) == ("unset", START, 2000.0)
    assert summary.min_score == 0.0
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


@pytest.mark.anyio
async def test_search_traces_lists_every_whole_trace_scored_or_not(spans_engine, reader):
    root, child = decode(export())
    healthy = later_copy(root, "a" * 32, status="ok")
    rootless = {**child, "trace_id": "c" * 32}
    other_app = {**root, "trace_id": "b" * 32, "app": "someone-else"}
    await store(spans_engine, [root, child, healthy, rootless, other_app])
    async with spans_engine.begin() as conn:  # no scores at all: the search must not need them
        await conn.execute(text("TRUNCATE scores"))

    found = await reader.search_traces(TraceQuery(app="medas"))

    # Newest first, the failed one and the healthy one; no rootless trace, no other app.
    assert [s.trace_id for s in found] == ["a" * 32, TRACE_ID.hex()]
    newest = found[0]
    assert (newest.status, newest.signature, newest.duration_ms) == ("ok", "request", 2000.0)
    # Ids and timing only: nothing a score or a span's content would fill.
    assert (newest.min_score, newest.failing_span_id, newest.error_message) == (None, None, None)
    assert await reader.search_traces(TraceQuery(app="someone-else")) == []


@pytest.mark.anyio
async def test_search_traces_keeps_to_the_window_and_the_limit(spans_engine, reader):
    root, child = decode(export())
    later = timedelta(hours=1)
    healthy = later_copy(root, "a" * 32)
    await store(spans_engine, [root, child, healthy])

    since = await reader.search_traces(TraceQuery(app="medas", since=START + later))
    until = await reader.search_traces(TraceQuery(app="medas", until=START + later))
    one = await reader.search_traces(TraceQuery(app="medas", limit=1))

    assert [s.trace_id for s in since] == ["a" * 32]
    assert [s.trace_id for s in until] == [TRACE_ID.hex()]
    assert [s.trace_id for s in one] == ["a" * 32]
