"""The eval runner: a seeded day through the graph, with the answer key. Needs TEST_DATABASE_URL."""

import json

import pytest

from agent.mcp_client import TraceClient
from api.traces import decode, store_spans
from eval.ground_truth import FAULTS
from eval.run import triage
from scripts.seed_traces import export, kinds
from tests.fakes import DIAGNOSIS, HashingEmbedder, fake_diagnoser
from tests.test_seed_traces import END


@pytest.mark.anyio
async def test_a_seeded_day_is_triaged_up_to_the_review_and_keeps_its_answer_key(
    spans_engine, postgres_url
):
    await store_spans(spans_engine, decode(export(END)))

    async with TraceClient(postgres_url) as traces:
        result = await triage(END, traces, HashingEmbedder(), fake_diagnoser(DIAGNOSIS))

    failed = {trace_id for trace_id, kind in kinds(END).items() if kind in FAULTS}
    assert set(result["failing_spans"]) == failed  # the healthy traces are not collected
    assert {t for cluster in result["clusters"] for t in cluster["trace_ids"]} == failed
    assert result["kinds"] == kinds(END)
    assert {d["cluster_id"] for d in result["diagnoses"]} == {
        cluster["cluster_id"] for cluster in result["clusters"]
    }
    assert result["diagnosis_failures"] == []
    assert len(result["model_usage"]) == len(result["clusters"])
    json.dumps(result)  # it is what the results file holds
