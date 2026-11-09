"""ProgressTransformer on the real graph, with fake traces and a fake chat model."""

import json
import warnings

import pytest

from agent.graph import build_graph
from agent.progress import COUNTED_KEYS, ProgressEvent, progress_events
from agent.state import TriageState
from tests.fakes import (
    DIAGNOSIS,
    FakeTraces,
    fake_context,
    fake_diagnoser,
    fake_model,
    span_tree,
    summary,
)

# Two failures at different steps make two clusters, c0 and c1.
FAILURES = [
    summary("t1", failing_span_name="retrieve", error_message="empty result for the drug query"),
    summary("t2", failing_span_name="generate", error_message="context length exceeded"),
]
TREES = {
    "t1": span_tree("t1", status_message="empty result for the drug query"),
    "t2": span_tree("t2", status_message="context length exceeded"),
}


async def stream_progress(model) -> tuple[list[ProgressEvent], dict]:
    """Run the graph through the v3 event stream; return its progress events and final state."""
    context = fake_context(FakeTraces(FAILURES, TREES), model)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the v3 protocol is flagged experimental
        stream = await build_graph().astream_events(
            {"target_app": "medas"}, version="v3", context=context
        )
        events = [e async for e in progress_events(stream)]
        return events, await stream.output()


def of(events: list[ProgressEvent], kind: str, node: str) -> list[ProgressEvent]:
    return [e for e in events if e["event"] == kind and e["node"] == node]


@pytest.mark.anyio
async def test_reports_each_node_and_one_branch_per_cluster():
    events, final = await stream_progress(fake_diagnoser(DIAGNOSIS))

    (collected,) = of(events, "node_finished", "collect_traces")
    assert collected["counts"] == {"failed_traces": 2}
    (clustered,) = of(events, "node_finished", "cluster_failures")
    assert clustered["counts"] == {"clusters": 2, "unclustered": 0}

    starts = of(events, "node_started", "diagnose_cluster")
    finishes = of(events, "node_finished", "diagnose_cluster")
    assert sorted(e["cluster_id"] for e in starts) == ["c0", "c1"]
    # The result event has no input, so its cluster id must come from the matching start.
    assert {e["task_id"]: e["cluster_id"] for e in finishes} == {
        e["task_id"]: e["cluster_id"] for e in starts
    }
    assert all(e["counts"] == {"diagnoses": 1} and "ok" not in e for e in finishes)

    assert events[-1]["node"] == "apply_actions"
    assert len(final["diagnoses"]) == 2


@pytest.mark.anyio
async def test_a_cluster_whose_diagnosis_failed_is_flagged_not_dropped():
    # The empty fake model raises on every call, so both diagnose branches record a failure.
    events, final = await stream_progress(fake_model())

    finishes = of(events, "node_finished", "diagnose_cluster")
    assert len(finishes) == 2
    assert all(e["ok"] is False and e["counts"] == {"diagnosis_failures": 1} for e in finishes)
    assert sorted(final["diagnosis_failures"]) == ["c0", "c1"]


@pytest.mark.anyio
async def test_progress_events_never_carry_trace_or_span_content():
    events, _ = await stream_progress(fake_diagnoser(DIAGNOSIS))

    allowed = set(ProgressEvent.__annotations__)
    assert all(set(e) <= allowed for e in events)
    wire = json.dumps(events)
    for secret in ("empty result", "context length", "t1", "t2", "retrieve", "medas"):
        assert secret not in wire


def test_every_counted_key_is_a_state_field():
    assert set(COUNTED_KEYS) <= set(TriageState.__annotations__)
