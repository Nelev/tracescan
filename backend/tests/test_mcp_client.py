"""Integration tests: the client against the real trace server, started as a subprocess, over a
seeded day in Postgres. Needs TEST_DATABASE_URL."""

from datetime import timedelta

import pytest

from agent.mcp_client import TraceClient
from api.traces import decode, store_spans
from eval.ground_truth import FAULTS
from scripts.seed_traces import export, kinds
from tests.test_seed_traces import END
from trace_store.models import FailedTraceQuery, SpanNode, TraceQuery, TraceSummary

EVERYTHING = FailedTraceQuery(app="medas", limit=200)


@pytest.fixture
async def traces(spans_engine, postgres_url):
    """One open session to the real trace server, over one seeded day."""
    await store_spans(spans_engine, decode(export(END)))
    async with TraceClient(postgres_url) as client:
        yield client


@pytest.mark.anyio
async def test_search_returns_typed_summaries_newest_first(traces):
    found = await traces.search_failed_traces(EVERYTHING)

    assert all(isinstance(t, TraceSummary) for t in found)
    assert {t.trace_id for t in found} == {t for t, kind in kinds(END).items() if kind in FAULTS}
    assert [t.start_time for t in found] == sorted((t.start_time for t in found), reverse=True)


@pytest.mark.anyio
async def test_search_traces_returns_every_seeded_trace(traces):
    found = await traces.search_traces(TraceQuery(app="medas", limit=200))

    # Faults, healthy requests and harmless errors alike: the judge decides which failed.
    assert {t.trace_id for t in found} == set(kinds(END))
    assert [t.start_time for t in found] == sorted((t.start_time for t in found), reverse=True)


@pytest.mark.anyio
async def test_query_datetimes_reach_the_server(traces):
    everything = await traces.search_failed_traces(EVERYTHING)
    since = END - timedelta(hours=12)

    found = await traces.search_failed_traces(EVERYTHING.model_copy(update={"since": since}))

    assert found == [t for t in everything if t.start_time >= since]
    assert 0 < len(found) < len(everything)


@pytest.mark.anyio
async def test_one_session_serves_several_calls(traces):
    first = await traces.search_failed_traces(EVERYTHING)
    for _ in range(3):
        assert await traces.search_failed_traces(EVERYTHING) == first


@pytest.mark.anyio
async def test_get_trace_tree_returns_a_typed_span_tree(traces):
    trace_id = (await traces.search_failed_traces(EVERYTHING))[0].trace_id

    tree = await traces.get_trace_tree(trace_id)

    assert isinstance(tree, SpanNode)
    assert tree.trace_id == trace_id
    assert tree.children
    with pytest.raises(RuntimeError, match="unknown trace_id"):
        await traces.get_trace_tree("0" * 32)


@pytest.mark.anyio
async def test_using_the_client_outside_its_context_raises():
    with pytest.raises(RuntimeError, match="async context manager"):
        await TraceClient("postgresql://not-opened").search_failed_traces(EVERYTHING)
