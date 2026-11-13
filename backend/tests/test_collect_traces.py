"""collect_traces against a fake client. The graph against the real trace server is in test_eval_run.py."""

from datetime import UTC, datetime

import pytest
from langgraph.types import Send

from agent.const import MAX_ISOLATED_DIAGNOSES
from agent.graph import (
    build_graph,
    join_scores,
    route_after_cluster,
    route_after_collect,
    route_after_review,
    route_after_scores,
)
from agent.schemas import Cluster, ClusterMethod
from agent.state import TriageState
from tests.fakes import FakeTraces, fake_context, summary
from trace_store.models import TraceSummary


async def run(fake: FakeTraces, state: TriageState) -> dict:
    return await build_graph().ainvoke(state, context=fake_context(fake))


@pytest.mark.anyio
async def test_summaries_become_plain_json_dicts():
    result = await run(FakeTraces([summary("t1")]), {"target_app": "medas"})
    [row] = result["traces"]
    assert isinstance(row, dict)
    assert TraceSummary.model_validate(row) == summary("t1")


@pytest.mark.anyio
async def test_every_trace_is_judged_and_only_the_failed_ones_are_clustered():
    healthy = summary("t2", status="ok")
    fake = FakeTraces([summary("t1", failing_span_name="retrieve"), healthy])
    result = await run(fake, {"target_app": "medas"})
    assert sorted(v["trace_id"] for v in result["verdicts"]) == ["t1", "t2"]
    [failed] = result["failed_traces"]
    assert (failed["trace_id"], failed["failing_span_name"]) == ("t1", "retrieve")
    assert failed["signature"] == "retrieve"  # the step, and its error type when it has one
    assert sorted(u["trace_id"] for u in result["judge_usage"]) == ["t1", "t2"]


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
async def test_graph_ends_early_when_the_window_has_no_traces():
    result = await run(FakeTraces(), {"target_app": "medas"})
    assert result["traces"] == []
    assert not result.get("verdicts") and "clusters" not in result


@pytest.mark.anyio
async def test_graph_ends_after_the_judge_when_no_trace_failed():
    result = await run(FakeTraces([summary("t1", status="ok")]), {"target_app": "medas"})
    assert result["failed_traces"] == []
    assert "clusters" not in result


@pytest.mark.anyio
async def test_naive_since_is_rejected():
    with pytest.raises(ValueError):
        await run(FakeTraces(), {"target_app": "medas", "since": "2026-11-05T09:30:00"})


def test_routes():
    def state(**fields) -> TriageState:
        return TriageState(target_app="medas", **fields)

    assert route_after_collect(state(traces=[])) == "__end__"
    traces = [{"trace_id": "t1"}, {"trace_id": "t2"}]
    sends = route_after_collect(state(traces=traces))
    assert isinstance(sends, list)
    assert [(s.node, s.arg) for s in sends] == [("score_trace", {"trace": t}) for t in traces]
    assert route_after_scores(state(failed_traces=[])) == "__end__"
    assert route_after_scores(state(failed_traces=[{"trace_id": "t"}])) == "cluster_failures"
    assert route_after_cluster(state()) == "__end__"
    clusters = [
        {"cluster_id": "c0", "method": "hdbscan", "exemplar_trace_ids": ["t1", "t2"]},
        {"cluster_id": "c1", "method": "step_error", "exemplar_trace_ids": ["t3"]},
    ]
    failed = [
        {"trace_id": t, "failing_span_id": f"s{t[1]}", "failing_span_name": "lookup"}
        for t in ("t2", "t3")
    ]
    sends = route_after_cluster(state(clusters=clusters, failed_traces=failed))
    assert isinstance(sends, list)
    assert [(s.node, s.arg) for s in sends] == [
        ("diagnose_cluster", {"cluster": c, "target_app": "medas", "failing_span": blamed})
        for c, blamed in zip(
            clusters,
            [{"trace_id": t, "span_id": f"s{t[1]}", "step": "lookup"} for t in ("t2", "t3")],
            strict=True,
        )
    ]
    (unblamed,) = route_after_cluster(state(clusters=clusters[:1]))
    assert isinstance(unblamed, Send) and unblamed.arg["failing_span"] is None
    assert route_after_review(state(decisions={"c0": "reject"})) == "__end__"
    assert route_after_review(state(decisions={"c0": "approve"})) == "apply_actions"


def test_join_scores_keeps_the_failed_traces_newest_first_with_their_failure():
    traces = [{"trace_id": t, "signature": "invoke_agent medas"} for t in ("t3", "t2", "t1")]
    verdict = {
        "failed": True,
        "score": 0.1,
        "blamed_span_id": "s",
        "failing_span_name": "execute_tool lookup",
        "error_type": "ToolReportedError",
        "error_message": "source unavailable",
    }
    state = TriageState(
        target_app="medas",
        traces=traces,
        # t2 went fine and t3 could not be judged (no verdict): only t1 failed.
        verdicts=[{"trace_id": "t1", **verdict}, {"trace_id": "t2", "failed": False}],
    )
    [failed] = join_scores(state)["failed_traces"]
    assert failed == {
        "trace_id": "t1",
        "failing_span_id": "s",
        "failing_span_name": "execute_tool lookup",
        "error_message": "source unavailable",
        "min_score": 0.1,
        "signature": "execute_tool lookup ToolReportedError",
    }


def test_one_trace_clusters_past_the_cap_get_no_diagnose_branch():
    def cluster(i: int, method: ClusterMethod) -> Cluster:
        trace = f"t{i}"
        return Cluster(
            cluster_id=f"c{i}",
            trace_ids=[trace],
            signature="lookup: error",
            exemplar_trace_ids=[trace],
            method=method,
        )

    isolated = [cluster(i, "isolated") for i in range(1, MAX_ISOLATED_DIAGNOSES + 3)]
    sends = route_after_cluster(
        TriageState(target_app="medas", clusters=[cluster(0, "hdbscan"), *isolated])
    )
    assert isinstance(sends, list)
    sent = [s.arg["cluster"]["cluster_id"] for s in sends]
    # Every real cluster, then the first isolated ones up to the cap, in clustering's order.
    assert sent == ["c0", *[c["cluster_id"] for c in isolated[:MAX_ISOLATED_DIAGNOSES]]]
