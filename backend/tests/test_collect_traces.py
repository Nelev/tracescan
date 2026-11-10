"""collect_traces against a fake client. The graph against the real trace server is in test_eval_run.py."""

from datetime import UTC, datetime

import pytest

from agent.graph import (
    build_graph,
    route_after_cluster,
    route_after_collect,
    route_after_join,
    route_after_review,
)
from agent.state import TriageState
from tests.fakes import FakeTraces, fake_context, summary
from trace_store.models import TraceSummary


async def run(fake: FakeTraces, state: TriageState) -> dict:
    return await build_graph().ainvoke(state, context=fake_context(fake))


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


def test_routes():
    def state(**fields) -> TriageState:
        return TriageState(target_app="medas", **fields)

    assert route_after_collect(state(failed_traces=[])) == "__end__"
    assert route_after_collect(state(failed_traces=[{"trace_id": "t"}])) == "cluster_failures"
    assert route_after_cluster(state()) == "__end__"
    clusters = [{"cluster_id": "c0"}, {"cluster_id": "c1"}]
    sends = route_after_cluster(state(clusters=clusters))
    assert [(s.node, s.arg) for s in sends] == [
        ("diagnose_cluster", {"cluster": c, "model_usage": []}) for c in clusters
    ]
    assert route_after_review(state(decisions={"c0": "reject"})) == "__end__"
    assert route_after_review(state(decisions={"c0": "approve"})) == "apply_actions"


def test_route_after_join_sends_back_only_clusters_without_a_verdict():
    usage = [
        {"cluster_id": "c0", "calls": 1, "tokens": 150, "cost_usd": 0.001},
        {"cluster_id": "c1", "calls": 1, "tokens": 0, "cost_usd": 0.0},
        {"cluster_id": "c2", "calls": 1, "tokens": 0, "cost_usd": 0.0},
    ]
    clusters = [{"cluster_id": c} for c in ("c0", "c1", "c2")]
    state = TriageState(
        target_app="medas",
        clusters=clusters,
        diagnoses=[{"cluster_id": "c0"}],  # diagnosed
        diagnosis_failures=["c2"],  # failed: also a verdict
        model_usage=usage,
    )
    (send,) = route_after_join(state)
    assert send.node == "diagnose_cluster"
    # The payload carries the cluster's own usage entries and nobody else's.
    assert send.arg == {"cluster": clusters[1], "model_usage": [usage[1]]}


def test_route_after_join_carries_on_when_every_cluster_has_a_verdict():
    state = TriageState(
        target_app="medas",
        clusters=[{"cluster_id": "c0"}, {"cluster_id": "c1"}],
        diagnoses=[{"cluster_id": "c0"}],
        diagnosis_failures=["c1"],
    )
    assert route_after_join(state) == "reproduce_failure"
