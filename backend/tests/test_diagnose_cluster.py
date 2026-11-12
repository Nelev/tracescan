"""diagnose_cluster against fake traces and a fake chat model, so no model is ever called."""

import asyncio
import json
from dataclasses import replace

import pytest
from langgraph.runtime import Runtime

from agent import model_guard
from agent.chunks import step_text
from agent.const import (
    HEALTHY_TWINS,
    MAX_MODEL_ATTEMPTS,
    MAX_PARALLEL_DIAGNOSES,
    UNSUPPORTED_CONFIDENCE_CAP,
)
from agent.evidence import FALLBACK_NOTE
from agent.graph import build_graph
from agent.nodes.diagnose_cluster import TAXONOMY, diagnose_cluster
from agent.schemas import Cluster, ClusterTask, Diagnosis, Evidence, HealthyMatch
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


TASK = ClusterTask(cluster=CLUSTER, target_app="medas", failing_spans={"t1": "s1"})


async def diagnose(model, healthy=None) -> dict:
    """One run of the node over CLUSTER, whose one exemplar is TREE."""
    context = replace(fake_context(FakeTraces(trees={"t1": TREE}), model), healthy=healthy)
    return await diagnose_cluster(TASK, Runtime(context=context))


class FakeHealthy:
    """A healthy-span store with fixed matches, recording what it was asked; or one that fails."""

    def __init__(self, matches: list[HealthyMatch], fail: bool = False) -> None:
        self.matches, self.fail, self.asked = matches, fail, []

    async def similar(self, text: str, step: str, app: str, k: int = 3) -> list[HealthyMatch]:
        if self.fail:
            raise RuntimeError("store down")
        self.asked.append((text, step, app, k))
        return self.matches


TWIN = HealthyMatch(trace_id="h1", span_id="hs", text="step: twin\noutcome: ok", distance=0.05)


@pytest.mark.anyio
async def test_the_model_sees_healthy_twins_of_the_failing_step_next_to_the_failure():
    healthy, model = FakeHealthy([TWIN]), fake_diagnoser(DIAGNOSIS)
    result = await diagnose(model, healthy)
    ((text, step, app, k),) = healthy.asked
    assert (text, step, app, k) == (step_text(TREE, "s1"), TREE.name, "medas", HEALTHY_TWINS)
    prompt = str(model.seen[0][1].content)
    assert text in prompt and TWIN.text in prompt and "do not cite them" in prompt
    assert result["diagnoses"][0]["evidence_check"] == "valid"


@pytest.mark.anyio
async def test_no_twins_and_no_store_leave_the_prompt_as_it_was():
    without, empty = fake_diagnoser(DIAGNOSIS), fake_diagnoser(DIAGNOSIS)
    await diagnose(without)
    await diagnose(empty, FakeHealthy([]))
    assert without.seen[0][1].content == empty.seen[0][1].content
    assert "Healthy calls" not in str(without.seen[0][1].content)


@pytest.mark.anyio
async def test_a_failing_store_does_not_fail_the_diagnosis(caplog):
    result = await diagnose(fake_diagnoser(DIAGNOSIS), FakeHealthy([], fail=True))
    assert result["diagnoses"][0]["cluster_id"] == "c0"
    assert "healthy twins of c0 not found: RuntimeError" in caplog.text


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
    """Counts how many span-tree fetches are in flight at once, per stage.

    The judge fetches each trace once, before any diagnosis; a second fetch of the same trace is
    a diagnose branch fetching its exemplar.
    """

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.seen: set[str] = set()
        self.active = {"judge": 0, "diagnose": 0}
        self.peak = {"judge": 0, "diagnose": 0}

    async def get_trace_tree(self, trace_id: str):
        stage = "diagnose" if trace_id in self.seen else "judge"
        self.seen.add(trace_id)
        self.active[stage] += 1
        self.peak[stage] = max(self.peak[stage], self.active[stage])
        await asyncio.sleep(0.01)
        self.active[stage] -= 1
        return await super().get_trace_tree(trace_id)


@pytest.mark.anyio
async def test_the_judge_runs_wider_than_the_diagnoser_and_the_diagnoser_keeps_its_cap():
    # Five failures stay below the HDBSCAN threshold, so each failing step is its own cluster.
    ids = [f"t{i}" for i in range(MAX_PARALLEL_DIAGNOSES + 1)]
    failures = [summary(i, failing_span_name=f"step_{i}") for i in ids]
    traces = SlowTraces(failures, {i: span_tree(i) for i in ids})
    context = fake_context(traces, fake_diagnoser(DIAGNOSIS))  # one exemplar per cluster
    await build_graph().ainvoke({"target_app": "medas"}, context=context)
    assert traces.peak == {"judge": len(ids), "diagnose": MAX_PARALLEL_DIAGNOSES}


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


@pytest.mark.anyio
async def test_a_transient_error_is_retried_until_it_clears():
    model = scripted_model(FakeApiError(503), FakeApiError(429), GOOD)
    result = await diagnose(model)

    (diagnosis,) = result["diagnoses"]
    assert diagnosis["evidence_check"] == "valid"
    assert len(model.seen) == 3
    # One entry for the cluster: three calls, only the last one answered.
    assert result["model_usage"] == [
        {"cluster_id": "c0", "calls": 3, "tokens": 150, "cost_usd": 0.001}
    ]


@pytest.mark.anyio
async def test_a_transient_error_that_never_clears_fails_the_cluster_within_the_budget():
    model = scripted_model(FakeApiError(429))  # repeats for ever
    result = await diagnose(model)

    assert result["diagnosis_failures"] == ["c0"]
    assert "diagnoses" not in result
    assert len(model.seen) == MAX_MODEL_ATTEMPTS
    assert result["model_usage"][0]["calls"] == MAX_MODEL_ATTEMPTS


@pytest.mark.anyio
async def test_an_error_that_asking_again_cannot_fix_fails_the_cluster_at_once():
    model = scripted_model(FakeApiError(401))
    result = await diagnose(model)
    assert result["diagnosis_failures"] == ["c0"]
    assert "diagnoses" not in result
    assert len(model.seen) == 1


@pytest.mark.anyio
async def test_retries_and_the_evidence_re_ask_share_one_budget(monkeypatch):
    monkeypatch.setattr(model_guard, "MAX_CLUSTER_TOKENS", 200)
    # A failed call costs no tokens; the answer costs 150 and cites a span it was not shown.
    model = scripted_model(FakeApiError(503), citing(("t9", "s9")), GOOD)
    result = await diagnose(model)

    assert len(model.seen) == 3  # 150 tokens is under the cap: the re-ask is allowed
    assert result["diagnoses"][0]["evidence_check"] == "corrected"
    assert result["model_usage"][0]["calls"] == 3


class FailingTraces(FakeTraces):
    async def get_trace_tree(self, trace_id: str):
        raise TimeoutError  # would be retryable if it came from the model


@pytest.mark.anyio
async def test_a_failure_before_any_model_call_is_a_failure_not_a_retry():
    # Left unfinished it would never use up the budget, and the graph would loop for ever.
    model = scripted_model(GOOD)
    context = fake_context(FailingTraces(), model)
    result = await diagnose_cluster(TASK, Runtime(context=context))

    assert result["diagnosis_failures"] == ["c0"]
    assert model.seen == []


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
    # One entry per cluster; the one that was retried made two calls.
    assert sorted(u["calls"] for u in result["model_usage"]) == [1, 2]


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


@pytest.mark.anyio
async def test_a_transient_error_on_the_re_ask_retries_that_call_only():
    model = scripted_model(citing(("t9", "s9")), FakeApiError(503), GOOD)
    result = await diagnose(model)

    assert len(model.seen) == 3  # the first answer is kept, not asked for again
    assert len(model.seen[2]) == 4  # the retried call is the re-ask, with the correction
    assert result["diagnoses"][0]["evidence_check"] == "corrected"
