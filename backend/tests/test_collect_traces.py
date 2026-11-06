"""collect_traces against a fake client, plus the compiled graph against the real trace server."""

from datetime import UTC, datetime

import pytest

from agent.context import TraceContext
from agent.graph import build_graph, route_after_cluster, route_after_collect, route_after_review
from agent.state import TriageState
from trace_store.models import FailedTraceQuery, TraceSummary


class FakeTraces:
    def __init__(self, found: list[TraceSummary] | None = None) -> None:
        self.found = found or []
        self.queries: list[FailedTraceQuery] = []

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        self.queries.append(query)
        return self.found


def summary(trace_id: str) -> TraceSummary:
    return TraceSummary.model_validate(
        {
            "trace_id": trace_id,
            "app": "medas",
            "start_time": "2026-11-05T10:00:00Z",
            "duration_ms": 120.0,
            "status": "error",
            "signature": "retrieve: empty result",
        }
    )


async def run(fake: FakeTraces, state: TriageState) -> dict:
    return await build_graph().ainvoke(state, context=TraceContext(fake))


@pytest.mark.anyio
async def test_summaries_become_plain_json_dicts():
    result = await run(FakeTraces([summary("t1")]), {"target_app": "medas"})
    [row] = result["failed_traces"]
    assert isinstance(row, dict)
    assert TraceSummary.model_validate(row) == summary("t1")


@pytest.mark.anyio
async def test_query_uses_target_app_and_window():
    fake = FakeTraces()
    await run(
        fake,
        {"target_app": "medas", "since": "2026-11-05T09:30:00Z", "until": "2026-11-06T00:00:00Z"},
    )
    [query] = fake.queries
    assert query.app == "medas"
    assert query.since == datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
    assert query.until == datetime(2026, 11, 6, tzinfo=UTC)


@pytest.mark.anyio
async def test_no_window_means_unbounded_query():
    fake = FakeTraces()
    await run(fake, {"target_app": "medas"})
    assert fake.queries[0].since is None and fake.queries[0].until is None


@pytest.mark.anyio
async def test_graph_ends_early_when_no_traces_failed():
    result = await run(FakeTraces(), {"target_app": "medas"})
    assert result["failed_traces"] == []
    assert "clusters" not in result


@pytest.mark.anyio
async def test_naive_since_is_rejected():
    with pytest.raises(ValueError):
        await run(FakeTraces(), {"target_app": "medas", "since": "2026-11-05T09:30:00"})


@pytest.mark.anyio
async def test_graph_collects_fixture_traces_through_the_real_server(traces):
    result = await run(traces, {"target_app": "medas"})
    assert [t["trace_id"] for t in result["failed_traces"]] == [
        "tr_tool_schema",
        "tr_retrieval_miss",
    ]


def test_routes():
    def state(**fields) -> TriageState:
        return TriageState(target_app="medas", **fields)

    assert route_after_collect(state(failed_traces=[])) == "__end__"
    assert route_after_collect(state(failed_traces=[{"trace_id": "t"}])) == "cluster_failures"
    assert route_after_cluster(state()) == "__end__"
    assert route_after_cluster(state(clusters=[{"cluster_id": "c0"}])) == "diagnose_cluster"
    assert route_after_review(state(decisions={"c0": "reject"})) == "__end__"
    assert route_after_review(state(decisions={"c0": "approve"})) == "apply_actions"
