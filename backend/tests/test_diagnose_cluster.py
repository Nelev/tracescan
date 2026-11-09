"""diagnose_cluster against fake traces and a fake chat model, so no model is ever called."""

import json
import os

import pytest
from langgraph.runtime import Runtime

from agent.clustering import cluster_summaries
from agent.context import TraceContext
from agent.graph import build_graph
from agent.mcp_client import TraceClient
from agent.model import build_diagnoser_model
from agent.nodes.diagnose_cluster import TAXONOMY, diagnose_cluster
from agent.schemas import Cluster, ClusterTask, Diagnosis
from tests.fakes import (
    DIAGNOSIS,
    FakeTraces,
    HashingEmbedder,
    fake_context,
    fake_diagnoser,
    span_tree,
    summary,
)
from trace_store.models import FailedTraceQuery

CLUSTER = Cluster(
    cluster_id="c0",
    trace_ids=["t1", "t2", "t3"],
    signature="retrieve: empty result",
    exemplar_trace_ids=["t1"],
    method="step_error",
)
TREE = span_tree("t1", span_id="s1", status_message="empty result for the interaction question")
# Two failures at different steps make two clusters.
FAILURES = [
    summary("t1", failing_span_name="retrieve", error_message="empty result"),
    summary("t2", failing_span_name="generate", error_message="context length exceeded"),
]


async def diagnose(model) -> dict:
    context = fake_context(FakeTraces(trees={"t1": TREE}), model)
    return await diagnose_cluster(ClusterTask(cluster=CLUSTER), Runtime(context=context))


async def run_graph(trees: dict, model) -> dict:
    context = fake_context(FakeTraces(FAILURES, trees), model)
    return await build_graph().ainvoke({"target_app": "medas"}, context=context)


@pytest.mark.anyio
async def test_returns_the_diagnosis_as_a_plain_dict_with_the_clusters_own_id():
    result = await diagnose(fake_diagnoser(DIAGNOSIS))
    (diagnosis,) = result["diagnoses"]
    json.dumps(diagnosis)  # plain JSON: nothing for the checkpoint serializer to warn on
    assert diagnosis["cluster_id"] == "c0"
    assert diagnosis["category"] == "retrieval_miss"
    assert Diagnosis.model_validate(diagnosis).evidence[0].span_id == "s1"


@pytest.mark.anyio
async def test_the_prompt_carries_the_taxonomy_and_only_the_exemplar_trees():
    model = fake_diagnoser(DIAGNOSIS)
    await diagnose(model)  # FakeTraces has no tree for t2 or t3, so fetching them would fail
    system, human = model.seen[0]
    assert system.content == TAXONOMY
    assert "retrieve: empty result" in human.content
    assert "empty result for the interaction question" in human.content


@pytest.mark.anyio
async def test_a_failing_cluster_is_recorded_not_raised():
    # No tree for t1 and a model that is never called: the node must not raise.
    node_context = fake_context(FakeTraces())
    result = await diagnose_cluster(ClusterTask(cluster=CLUSTER), Runtime(context=node_context))
    assert result == {"diagnosis_failures": ["c0"]}


@pytest.mark.anyio
async def test_the_graph_diagnoses_every_cluster():
    result = await run_graph({t: span_tree(t) for t in ("t1", "t2")}, fake_diagnoser(DIAGNOSIS))
    assert sorted(d["cluster_id"] for d in result["diagnoses"]) == ["c0", "c1"]
    assert result.get("diagnosis_failures", []) == []


@pytest.mark.anyio
async def test_a_failed_cluster_does_not_cost_the_others_their_diagnosis():
    result = await run_graph({"t1": span_tree("t1")}, fake_diagnoser(DIAGNOSIS))  # no tree for t2
    assert len(result["diagnoses"]) == 1
    assert len(result["diagnosis_failures"]) == 1
    assert {result["diagnoses"][0]["cluster_id"], *result["diagnosis_failures"]} == {"c0", "c1"}


@pytest.mark.skipif(not os.environ.get("RUN_LLM"), reason="set RUN_LLM=1 (and OPENROUTER_API_KEY)")
@pytest.mark.anyio
async def test_the_real_model_diagnoses_every_fixture_cluster():
    async with TraceClient() as traces:
        failed = await traces.search_failed_traces(FailedTraceQuery(app="medas"))
        clusters, _ = cluster_summaries(failed, HashingEmbedder())
        context = TraceContext(traces, HashingEmbedder(), build_diagnoser_model())
        for cluster in clusters:
            result = await diagnose_cluster(ClusterTask(cluster=cluster), Runtime(context=context))
            Diagnosis.model_validate(result["diagnoses"][0])
