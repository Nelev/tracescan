"""diagnose_cluster against fake traces and a fake chat model, so no model is ever called."""

import json
import os

import pytest
from langgraph.runtime import Runtime

from agent.clustering import cluster_summaries
from agent.context import TraceContext
from agent.mcp_client import TraceClient
from agent.model import build_diagnoser_model
from agent.nodes.diagnose_cluster import TAXONOMY, diagnose_cluster
from agent.schemas import Cluster, ClusterTask, Diagnosis
from tests.fakes import FakeTraces, HashingEmbedder, fake_context, fake_diagnoser
from trace_store.models import FailedTraceQuery, SpanNode

CLUSTER = Cluster(
    cluster_id="c0",
    trace_ids=["t1", "t2", "t3"],
    signature="retrieve: empty result",
    exemplar_trace_ids=["t1"],
    method="step_error",
)
TREE = SpanNode.model_validate(
    {
        "span_id": "s1",
        "trace_id": "t1",
        "name": "retrieve",
        "start_time": "2026-11-05T10:00:00Z",
        "end_time": "2026-11-05T10:00:01Z",
        "status": "error",
        "status_message": "empty result for the interaction question",
    }
)
# What a model might answer, with a cluster id of its own invention.
ANSWER = Diagnosis.model_validate(
    {
        "cluster_id": "made-up",
        "category": "retrieval_miss",
        "root_cause": "The retriever's filter excludes the drug-interaction category.",
        "suggested_fix": "Include the category in the filter.",
        "confidence": 0.7,
        "evidence": [{"trace_id": "t1", "span_id": "s1", "note": "retrieve returned nothing"}],
    }
)


async def diagnose(model) -> dict:
    context = fake_context(FakeTraces(trees={"t1": TREE}), model)
    return await diagnose_cluster(ClusterTask(cluster=CLUSTER), Runtime(context=context))


@pytest.mark.anyio
async def test_returns_the_diagnosis_as_a_plain_dict_with_the_clusters_own_id():
    result = await diagnose(fake_diagnoser(ANSWER))
    (diagnosis,) = result["diagnoses"]
    json.dumps(diagnosis)  # plain JSON: nothing for the checkpoint serializer to warn on
    assert diagnosis["cluster_id"] == "c0"
    assert diagnosis["category"] == "retrieval_miss"
    assert Diagnosis.model_validate(diagnosis).evidence[0].span_id == "s1"


@pytest.mark.anyio
async def test_the_prompt_carries_the_taxonomy_and_only_the_exemplar_trees():
    model = fake_diagnoser(ANSWER)
    await diagnose(model)  # FakeTraces has no tree for t2 or t3, so fetching them would fail
    system, human = model.seen[0]
    assert system.content == TAXONOMY
    assert "retrieve: empty result" in human.content
    assert "empty result for the interaction question" in human.content


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
