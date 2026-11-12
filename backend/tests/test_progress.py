"""ProgressTransformer on the real graph, with fake traces and a fake chat model."""

import json
import warnings
from typing import Any

import pytest

from agent.graph import build_graph
from agent.progress import COUNTED_KEYS, progress_events
from agent.schemas import ProgressEvent
from agent.state import TriageState
from tests.fakes import (
    DIAGNOSIS,
    FakeApiError,
    FakeStructuredModel,
    FakeTraces,
    fake_context,
    fake_diagnoser,
    fake_model,
    first_span_shown,
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


# Plain dicts: ProgressEvent's keys are all optional, so the tests index them without narrowing.
Event = dict[str, Any]


async def stream_progress(model, traces=None) -> tuple[list[Event], dict[str, Any]]:
    """Run the graph through the v3 event stream; return its progress events and final state."""
    context = fake_context(traces or FakeTraces(FAILURES, TREES), model)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the v3 protocol is flagged experimental
        stream = await build_graph().astream_events(
            {"target_app": "medas"}, version="v3", context=context
        )
        events: list[Event] = [dict(e) async for e in progress_events(stream)]
        final = await stream.output()
        assert final is not None
        return events, final


def of(events: list[Event], kind: str, node: str) -> list[Event]:
    return [e for e in events if e["event"] == kind and e["node"] == node]


@pytest.mark.anyio
async def test_reports_each_node_and_one_branch_per_cluster():
    events, final = await stream_progress(fake_diagnoser(DIAGNOSIS))

    (collected,) = of(events, "node_finished", "collect_traces")
    assert collected["counts"] == {"traces": 2}
    # One judge branch per trace; none reports its own start or end, only how many are judged.
    judging = [e for e in events if e["node"] == "score_trace"]
    assert judging == [
        {"event": "node_progress", "node": "score_trace", "counts": {"done": 1, "total": 2}}
    ]
    (scored,) = of(events, "node_finished", "join_scores")
    assert scored["counts"] == {"failed_traces": 2}
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

    # The run stops at the review: the node pauses, it neither finishes nor fails.
    assert (events[-1]["node"], events[-1]["event"]) == ("human_review", "node_paused")
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
async def test_a_retried_cluster_is_still_one_branch_and_the_next_stage_starts_once():
    failed_once = []

    def answer(messages):
        if not failed_once:
            failed_once.append(1)
            raise FakeApiError(503)  # whichever cluster calls first, once
        return DIAGNOSIS.model_copy(update={"evidence": [first_span_shown(messages)]})

    events, final = await stream_progress(FakeStructuredModel(messages=iter(()), answer=answer))

    starts = of(events, "node_started", "diagnose_cluster")
    assert sorted(e["cluster_id"] for e in starts) == ["c0", "c1"]
    finishes = of(events, "node_finished", "diagnose_cluster")
    assert all(e["counts"] == {"diagnoses": 1} and "ok" not in e for e in finishes)
    assert len(of(events, "node_started", "draft_proposals")) == 1  # after both branches
    assert len(final["diagnoses"]) == 2


@pytest.mark.anyio
async def test_progress_events_never_carry_trace_or_span_content():
    events, _ = await stream_progress(fake_diagnoser(DIAGNOSIS))

    allowed = set(ProgressEvent.__annotations__)
    assert all(set(e) <= allowed for e in events)
    wire = json.dumps(events)
    for secret in ("empty result", "context length", "t1", "t2", "retrieve", "medas"):
        assert secret not in wire


@pytest.mark.anyio
async def test_judging_reports_each_quarter_but_the_last():
    ids = [f"t{i}" for i in range(9)]
    traces = FakeTraces(
        [summary(i, failing_span_name="retrieve") for i in ids], {i: span_tree(i) for i in ids}
    )
    events, _ = await stream_progress(fake_model(), traces)

    judged = [e["counts"] for e in events if e["event"] == "node_progress"]
    # 9 traces: a quarter is passed at 3, 5 and 7; the 9th is join_scores starting.
    assert judged == [{"done": n, "total": 9} for n in (3, 5, 7)]
    first_judged = events.index(next(e for e in events if e["event"] == "node_progress"))
    collected = of(events, "node_finished", "collect_traces")[0]
    assert (
        events.index(collected)
        < first_judged
        < events.index(of(events, "node_started", "join_scores")[0])
    )


def test_every_counted_key_is_a_state_field():
    assert set(COUNTED_KEYS) <= set(TriageState.__annotations__)
