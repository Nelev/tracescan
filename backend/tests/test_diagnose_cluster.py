"""diagnose_cluster against fake traces and a fake chat model, so no model is ever called."""

import asyncio
import json

import pytest
from langgraph.runtime import Runtime

from agent import model_guard
from agent.const import MAX_MODEL_ATTEMPTS, MAX_PARALLEL_BRANCHES, UNSUPPORTED_CONFIDENCE_CAP
from agent.evidence import FALLBACK_NOTE
from agent.graph import build_graph
from agent.nodes.diagnose_cluster import TAXONOMY, diagnose_cluster
from agent.schemas import Cluster, ClusterTask, Diagnosis, Evidence
from tests.fakes import (
    DIAGNOSIS,
    FakeApiError,
    FakeStructuredModel,
    FakeTraces,
    fake_context,
    fake_diagnoser,
    first_span_shown,
    scripted_model,
    span_tree,
    summary,
)

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


async def diagnose(model, usage: list[dict] | None = None) -> dict:
    """One run of the node. `usage` is what the router would pass from earlier runs."""
    context = fake_context(FakeTraces(trees={"t1": TREE}), model)
    task = ClusterTask(cluster=CLUSTER, model_usage=usage or [])
    return await diagnose_cluster(task, Runtime(context=context))


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
    assert diagnosis["evidence_check"] == "valid"


@pytest.mark.anyio
async def test_the_prompt_carries_the_taxonomy_and_only_the_exemplar_trees():
    model = fake_diagnoser(DIAGNOSIS)
    await diagnose(model)  # FakeTraces has no tree for t2 or t3, so fetching them would fail
    system, human = model.seen[0]
    assert system.content == TAXONOMY
    assert "retrieve: empty result" in human.content
    assert "empty result for the interaction question" in human.content


@pytest.mark.anyio
async def test_the_graph_diagnoses_every_cluster():
    result = await run_graph({t: span_tree(t) for t in ("t1", "t2")}, fake_diagnoser(DIAGNOSIS))
    assert sorted(d["cluster_id"] for d in result["diagnoses"]) == ["c0", "c1"]
    assert {d["evidence_check"] for d in result["diagnoses"]} == {"valid"}
    assert result.get("diagnosis_failures", []) == []


@pytest.mark.anyio
async def test_a_failed_cluster_does_not_cost_the_others_their_diagnosis():
    # The first diagnosis call fails for good (401); the other cluster's call answers.
    result = await run_graph({"t1": span_tree("t1")}, scripted_model(FakeApiError(401), DIAGNOSIS))
    diagnosed = [d["cluster_id"] for d in result["diagnoses"]]
    assert len(diagnosed) == 1  # one cluster diagnosed, the other recorded as failed
    assert sorted(diagnosed + result["diagnosis_failures"]) == ["c0", "c1"]


class SlowTraces(FakeTraces):
    """Counts how many span-tree fetches are in flight at once."""

    active = peak = 0

    async def get_trace_tree(self, trace_id: str):
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return await super().get_trace_tree(trace_id)


@pytest.mark.anyio
async def test_the_graph_diagnoses_at_most_the_capped_number_of_clusters_at_once():
    # Five failures stay below the HDBSCAN threshold, so each failing step is its own cluster.
    ids = [f"t{i}" for i in range(MAX_PARALLEL_BRANCHES + 1)]
    failures = [summary(i, failing_span_name=f"step_{i}") for i in ids]
    traces = SlowTraces(failures, {i: span_tree(i) for i in ids})
    context = fake_context(traces, fake_diagnoser(DIAGNOSIS))  # one exemplar per cluster
    await build_graph().ainvoke({"target_app": "medas"}, context=context)
    assert traces.peak == MAX_PARALLEL_BRANCHES


def citing(*pairs: tuple[str, str]) -> Diagnosis:
    evidence = [Evidence(trace_id=t, span_id=s, note="x") for t, s in pairs]
    return DIAGNOSIS.model_copy(update={"evidence": evidence})


GOOD = citing(("t1", "s1"))  # TREE is trace t1 with the failing span s1


@pytest.mark.anyio
async def test_a_valid_citation_costs_one_model_call():
    model = scripted_model(GOOD)
    (diagnosis,) = (await diagnose(model))["diagnoses"]
    assert len(model.seen) == 1
    assert diagnosis["evidence_check"] == "valid"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fake",
    [("t9", "s9"), ("t1", "nope"), ("t2", "t2_root")],
    ids=["unknown trace", "unknown span", "a trace of the cluster that was not shown"],
)
async def test_a_fake_citation_is_retried_once_with_the_valid_spans_listed(fake):
    model = scripted_model(citing(fake), GOOD)
    (diagnosis,) = (await diagnose(model))["diagnoses"]

    assert len(model.seen) == 2
    retry = model.seen[1]
    assert len(retry) == 4  # system, prompt, its own answer, the correction
    assert f"{fake[0]}/{fake[1]}" in retry[3].content
    assert "t1: s1" in retry[3].content
    assert diagnosis["evidence_check"] == "corrected"
    assert [(e["trace_id"], e["span_id"]) for e in diagnosis["evidence"]] == [("t1", "s1")]
    assert diagnosis["confidence"] == DIAGNOSIS.confidence  # a corrected answer keeps it


@pytest.mark.anyio
async def test_a_citation_that_stays_fake_is_dropped_and_the_confidence_capped():
    mixed = citing(("t1", "s1"), ("t9", "s9"))
    model = scripted_model(mixed)  # answers the same after the correction
    result = await diagnose(model)

    (diagnosis,) = result["diagnoses"]  # not a failed cluster
    assert "diagnosis_failures" not in result
    assert len(model.seen) == 2  # retried once, not more
    assert diagnosis["evidence_check"] == "unsupported"
    assert [(e["trace_id"], e["span_id"]) for e in diagnosis["evidence"]] == [("t1", "s1")]
    assert diagnosis["confidence"] == UNSUPPORTED_CONFIDENCE_CAP


@pytest.mark.anyio
async def test_with_no_valid_citation_left_the_clusters_own_failing_span_is_cited():
    (diagnosis,) = (await diagnose(scripted_model(citing(("t9", "s9")))))["diagnoses"]
    assert diagnosis["evidence_check"] == "unsupported"
    (evidence,) = diagnosis["evidence"]
    assert (evidence["trace_id"], evidence["span_id"]) == ("t1", "s1")
    assert evidence["note"] == FALLBACK_NOTE
    assert diagnosis["confidence"] == UNSUPPORTED_CONFIDENCE_CAP


@pytest.mark.anyio
async def test_a_failing_retry_is_a_failed_cluster_not_a_dropped_one():
    calls = []

    def answer(_):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("model down")
        return citing(("t9", "s9"))

    result = await diagnose(FakeStructuredModel(messages=iter(()), answer=answer))
    assert result["diagnosis_failures"] == ["c0"]
    assert "diagnoses" not in result
    # The failed cluster still reports what it spent: both calls, the first one answered.
    assert result["model_usage"] == [
        {"cluster_id": "c0", "calls": 2, "tokens": 150, "cost_usd": pytest.approx(0.001)}
    ]


@pytest.mark.anyio
async def test_a_cluster_puts_what_its_model_calls_cost_in_state():
    result = await diagnose(scripted_model(GOOD))
    (usage,) = result["model_usage"]
    json.dumps(usage)  # plain numbers and strings: nothing for the checkpoint serializer to warn on
    assert usage == {"cluster_id": "c0", "calls": 1, "tokens": 150, "cost_usd": 0.001}


@pytest.mark.anyio
async def test_the_graph_collects_one_usage_entry_per_cluster():
    result = await run_graph({t: span_tree(t) for t in ("t1", "t2")}, fake_diagnoser(DIAGNOSIS))
    assert sorted(u["cluster_id"] for u in result["model_usage"]) == ["c0", "c1"]


def earlier_runs(calls: int, tokens: int = 0) -> list[dict]:
    """The cluster's `model_usage` entries from `calls` earlier runs, as the router passes them."""
    entry = {"cluster_id": "c0", "calls": 1, "tokens": tokens // calls, "cost_usd": 0.0}
    return [entry] * calls


@pytest.mark.anyio
async def test_a_transient_error_with_budget_left_leaves_the_cluster_unfinished():
    model = scripted_model(FakeApiError(503))
    result = await diagnose(model)

    # No verdict: the graph runs the node again. Only the spend is reported.
    assert result == {"model_usage": [{"cluster_id": "c0", "calls": 1, "tokens": 0, "cost_usd": 0}]}


@pytest.mark.anyio
async def test_a_transient_error_with_no_budget_left_fails_the_cluster():
    model = scripted_model(FakeApiError(503))
    result = await diagnose(model, earlier_runs(MAX_MODEL_ATTEMPTS - 1))

    assert result["diagnosis_failures"] == ["c0"]
    assert result["model_usage"][0]["calls"] == 1  # this run only, not the earlier ones


@pytest.mark.anyio
async def test_an_error_that_asking_again_cannot_fix_fails_the_cluster_at_once():
    result = await diagnose(scripted_model(FakeApiError(401)))
    assert result["diagnosis_failures"] == ["c0"]
    assert "diagnoses" not in result


@pytest.mark.anyio
async def test_the_budget_is_checked_before_the_run_and_the_model_is_not_called():
    model = scripted_model(GOOD)
    result = await diagnose(model, earlier_runs(MAX_MODEL_ATTEMPTS))

    assert result == {"diagnosis_failures": ["c0"]}
    assert model.seen == []


@pytest.mark.anyio
async def test_a_re_run_waits_and_then_diagnoses_like_a_first_run():
    result = await diagnose(scripted_model(GOOD), earlier_runs(1))
    (diagnosis,) = result["diagnoses"]
    assert diagnosis["evidence_check"] == "valid"
    assert result["model_usage"][0]["calls"] == 1


@pytest.mark.anyio
async def test_earlier_spend_counts_against_the_evidence_re_ask(monkeypatch):
    monkeypatch.setattr(model_guard, "MAX_CLUSTER_TOKENS", 200)
    model = scripted_model(citing(("t9", "s9")))  # this run alone costs 150, under the cap
    result = await diagnose(model, earlier_runs(1, tokens=100))

    assert len(model.seen) == 1  # 100 earlier + 150 now is over: no re-ask
    assert result["diagnoses"][0]["evidence_check"] == "unsupported"


class FailingTraces(FakeTraces):
    async def get_trace_tree(self, trace_id: str):
        raise TimeoutError  # would be retryable if it came from the model


@pytest.mark.anyio
async def test_a_failure_before_any_model_call_is_a_failure_not_a_retry():
    # Left unfinished it would never use up the budget, and the graph would loop for ever.
    model = scripted_model(GOOD)
    context = fake_context(FailingTraces(), model)
    result = await diagnose_cluster(ClusterTask(cluster=CLUSTER), Runtime(context=context))

    assert result["diagnosis_failures"] == ["c0"]
    assert model.seen == []


async def run_one_cluster(model) -> dict:
    """The whole graph over one failed trace, so one cluster, c0."""
    failure = summary("t1", failing_span_name="retrieve", error_message="empty result")
    context = fake_context(FakeTraces([failure], {"t1": TREE}), model)
    return await build_graph().ainvoke({"target_app": "medas"}, context=context)


@pytest.mark.anyio
async def test_the_graph_runs_the_node_again_after_a_transient_error():
    model = scripted_model(FakeApiError(503), FakeApiError(429), GOOD)
    result = await run_one_cluster(model)

    (diagnosis,) = result["diagnoses"]
    assert diagnosis["evidence_check"] == "valid"
    assert result.get("diagnosis_failures", []) == []
    assert len(model.seen) == 3
    # One entry per run; the two failed runs spent a call and no tokens.
    assert [(u["calls"], u["tokens"]) for u in result["model_usage"]] == [(1, 0), (1, 0), (1, 150)]


@pytest.mark.anyio
async def test_the_graph_stops_when_errors_never_clear_and_records_the_failure():
    model = scripted_model(FakeApiError(429))  # repeats for ever
    result = await run_one_cluster(model)

    assert result["diagnosis_failures"] == ["c0"]
    assert result.get("diagnoses", []) == []
    assert len(model.seen) == MAX_MODEL_ATTEMPTS
    assert len(result["model_usage"]) == MAX_MODEL_ATTEMPTS


@pytest.mark.anyio
async def test_the_graph_does_not_run_the_node_again_after_a_fatal_error():
    model = scripted_model(FakeApiError(401))
    result = await run_one_cluster(model)

    assert result["diagnosis_failures"] == ["c0"]
    assert len(model.seen) == 1


@pytest.mark.anyio
async def test_one_cluster_running_again_does_not_hold_back_or_repeat_the_others():
    failed_once = []

    def answer(messages):
        if not failed_once:
            failed_once.append(1)
            raise FakeApiError(503)  # whichever cluster calls first
        return DIAGNOSIS.model_copy(update={"evidence": [first_span_shown(messages)]})

    model = FakeStructuredModel(messages=iter(()), answer=answer)
    result = await run_graph({t: span_tree(t) for t in ("t1", "t2")}, model)

    assert sorted(d["cluster_id"] for d in result["diagnoses"]) == ["c0", "c1"]  # each only once
    assert result.get("diagnosis_failures", []) == []
    assert len(result["model_usage"]) == 3  # two first runs and one re-run


@pytest.mark.anyio
async def test_a_spent_budget_keeps_the_diagnosis_as_unsupported_instead_of_asking_again(
    monkeypatch,
):
    monkeypatch.setattr(model_guard, "MAX_CLUSTER_TOKENS", 100)  # the first call alone costs 150
    model = scripted_model(citing(("t9", "s9")))
    result = await diagnose(model)

    assert len(model.seen) == 1  # the evidence re-ask was refused
    assert "diagnosis_failures" not in result  # and the cluster was kept
    (diagnosis,) = result["diagnoses"]
    assert diagnosis["evidence_check"] == "unsupported"
    assert diagnosis["confidence"] == UNSUPPORTED_CONFIDENCE_CAP
    (evidence,) = diagnosis["evidence"]
    assert (evidence["trace_id"], evidence["span_id"]) == ("t1", "s1")  # the failing span
