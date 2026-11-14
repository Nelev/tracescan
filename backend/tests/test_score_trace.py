"""score_trace against fake traces and a fake judge model, so no model is ever called."""

import json
from dataclasses import replace

import pytest
from langgraph.runtime import Runtime

from agent import model_guard
from agent.chunks import step_key, step_text
from agent.const import (
    MAX_MODEL_ATTEMPTS,
    REPEATED_ROUNDS,
    SYMPTOM_EMPTY,
    SYMPTOM_REPEATED,
    SYMPTOM_REPLY,
)
from agent.context import ClosedTraces
from agent.judge import error_type, failure_fields, rounds_per_tool
from agent.nodes.score_trace import score_trace
from agent.schemas import TraceTask, TraceVerdict
from tests.fakes import FakeApiError, FakeTraces, fake_context, span_tree, summary
from tests.fakes import scripted_model as scripted
from trace_store.models import SpanNode

# A request whose tool reported a failure without raising: only `error.type` says so.
TREE = span_tree(
    "t1",
    span_id="root",
    name="invoke_agent medas",
    children=[
        span_tree(
            "t1",
            span_id="tool",
            parent_span_id="root",
            name="execute_tool lookup",
            status_message="source unavailable",
            attributes={"error.type": "ToolReportedError"},
        )
    ],
)
FAILED = TraceVerdict(
    reason="The lookup tool failed.", score=0.1, blamed_span_id="tool", attribution="app"
)
FINE = TraceVerdict(reason="Every step worked.", score=1.0)


def judge_context(model, trees=None, judge_model=None):
    """A run's context with `model` as its judge (unless `judge_model` is given)."""
    traces = FakeTraces(trees={"t1": TREE}) if trees is None else trees
    return replace(fake_context(traces, model), judge_model=judge_model)


async def score(model, trees=None, judge_model=None, context=None) -> dict:
    """One judge branch for t1; pass `context` to run several branches of one run."""
    context = context or judge_context(model, trees, judge_model)
    return await score_trace(
        TraceTask(trace=summary("t1").model_dump(mode="json")), Runtime(context=context)
    )


@pytest.mark.anyio
async def test_a_trace_that_went_fine_gets_its_verdict_and_one_usage_entry():
    result = await score(scripted(FINE))
    json.dumps(result)  # plain JSON, ready for graph state
    (verdict,) = result["verdicts"]
    assert (verdict["trace_id"], verdict["failed"]) == ("t1", False)
    assert "failing_span_name" not in verdict
    assert result["judge_usage"] == [
        {"trace_id": "t1", "calls": 1, "tokens": 150, "cost_usd": 0.001}
    ]
    assert "judge_failures" not in result


@pytest.mark.anyio
async def test_a_healthy_pick_carries_the_text_it_is_embedded_as():
    tree = span_tree(
        "t1",
        span_id="root",
        name="invoke_agent medas",
        status="ok",
        children=[
            span_tree(
                "t1", span_id="tool", parent_span_id="root", name="execute_tool lookup", status="ok"
            )
        ],
    )
    fine = FINE.model_copy(update={"healthy_span_ids": ["tool"]})
    (verdict,) = (await score(scripted(fine), trees=FakeTraces(trees={"t1": tree})))["verdicts"]
    assert verdict["healthy_spans"] == [
        {"span_id": "tool", **step_key(tree, "tool"), "text": step_text(tree, "tool")}
    ]
    assert "healthy_span_ids" not in verdict


@pytest.mark.anyio
async def test_a_failed_trace_carries_what_clustering_reads_of_its_blamed_span():
    (verdict,) = (await score(scripted(FAILED)))["verdicts"]
    assert verdict["blamed_span_id"] == "tool"
    assert verdict["failing_span_name"] == "execute_tool lookup"
    assert verdict["error_type"] == "ToolReportedError"
    assert verdict["error_message"] == "source unavailable"
    assert verdict["healthy_spans"] == []


@pytest.mark.anyio
async def test_the_judge_model_is_used_when_set():
    diagnoser, judge = scripted(FINE), scripted(FAILED)
    (verdict,) = (await score(diagnoser, judge_model=judge))["verdicts"]
    assert verdict["failed"] and len(judge.seen) == 1 and not diagnoser.seen


@pytest.mark.anyio
async def test_a_model_error_that_persists_records_the_trace_as_failed_to_judge_with_its_spend():
    result = await score(scripted(FakeApiError(503)))
    assert result["judge_failures"] == ["t1"]
    assert "verdicts" not in result
    assert result["judge_usage"] == [
        {"trace_id": "t1", "calls": MAX_MODEL_ATTEMPTS, "tokens": 0, "cost_usd": 0.0}
    ]


@pytest.mark.anyio
async def test_a_trace_whose_judge_was_throttled_once_is_still_judged():
    result = await score(scripted(FakeApiError(429), FINE))
    assert "judge_failures" not in result
    assert [v["trace_id"] for v in result["verdicts"]] == ["t1"]
    assert result["judge_usage"][0]["calls"] == 2


@pytest.mark.anyio
async def test_a_tree_that_cannot_be_fetched_is_recorded_without_a_model_call():
    model = scripted(FINE)
    result = await score(model, trees=ClosedTraces())
    assert result["judge_failures"] == ["t1"]
    assert result["judge_usage"][0]["calls"] == 0 and not model.seen


def test_error_type_reads_the_attribute_then_the_exception_event():
    assert error_type(TREE.children[0]) == "ToolReportedError"
    raised = span_tree(
        "t2", events=[{"name": "exception", "attributes": {"exception.type": "TimeoutError"}}]
    )
    assert error_type(raised) == "TimeoutError"
    assert error_type(span_tree("t3")) is None


def test_failure_fields_finds_a_nested_span():
    assert failure_fields(TREE, "root")["failing_span_name"] == "invoke_agent medas"


# --- the run's budget


@pytest.mark.anyio
async def test_each_judged_trace_adds_its_spend_to_the_runs():
    model = scripted(FINE)
    context = judge_context(model)
    await score(model, context=context)
    await score(model, context=context)
    assert (context.run_spent.calls, context.run_spent.tokens) == (2, 300)


@pytest.mark.anyio
async def test_a_trace_is_not_judged_once_the_run_is_past_its_budget(monkeypatch):
    monkeypatch.setattr(model_guard, "MAX_RUN_TOKENS", 100)  # one judge call alone costs 150
    model = scripted(FINE)
    context = judge_context(model)
    judged = await score(model, context=context)
    skipped = await score(model, context=context)
    assert [v["trace_id"] for v in judged["verdicts"]] == ["t1"]
    # Skipped before the fetch and the call: recorded as not judged, with nothing spent.
    assert skipped["judge_failures"] == ["t1"] and "verdicts" not in skipped
    assert skipped["judge_usage"] == [{"trace_id": "t1", "calls": 0, "tokens": 0, "cost_usd": 0.0}]
    assert len(model.seen) == 1


def silent(trace_id: str, steps: list[tuple[str, dict]], **root) -> SpanNode:
    """A request whose spans all completed: `steps` in time order, one second apart, each a name
    and its attributes, under a root with `root`'s fields."""
    children = [
        span_tree(
            trace_id,
            span_id=f"s{i}",
            parent_span_id="root",
            name=name,
            status="ok",
            status_message=None,
            attributes=attributes,
            start_time=f"2026-11-05T10:00:{i:02}Z",
            end_time=f"2026-11-05T10:00:{i:02}.5Z",
        )
        for i, (name, attributes) in enumerate(steps, start=1)
    ]
    fields = {"status": "ok", "status_message": None, "name": "invoke_agent medas"} | root
    return span_tree(trace_id, span_id="root", children=children, **fields)


CHAT = ("chat m", {"gen_ai.operation.name": "chat"})
SEARCH = ("execute_tool search", {"gen_ai.operation.name": "execute_tool"})


def test_calls_made_together_count_as_one_round():
    tree = silent("t", [CHAT, SEARCH, SEARCH, SEARCH, CHAT, SEARCH, CHAT])

    assert rounds_per_tool(tree) == {"execute_tool search": 2}


def test_a_tool_asked_for_round_after_round_is_a_repeated_step():
    tree = silent("t", [CHAT, SEARCH] * REPEATED_ROUNDS + [CHAT])

    assert failure_fields(tree, "s1")["error_message"] == SYMPTOM_REPEATED


def test_a_reply_not_in_the_asked_for_shape_is_said_so():
    tree = silent("t", [CHAT, SEARCH, CHAT], attributes={"medas.reply.format": "no_severity"})

    assert failure_fields(tree, "s3")["error_message"] == SYMPTOM_REPLY


def test_a_search_that_found_nothing_is_said_so():
    empty = ("retrieval record_chunks", {"retrieval.hits": 0})
    tree = silent("t", [CHAT, SEARCH, empty, CHAT])

    assert failure_fields(tree, "s3")["error_message"] == SYMPTOM_EMPTY


def test_a_silent_failure_with_nothing_to_show_has_no_message():
    fields = failure_fields(silent("t", [CHAT, SEARCH, CHAT]), "s3")

    assert fields == {"failing_span_name": "chat m", "error_type": None, "error_message": None}


def test_a_step_that_recorded_its_error_keeps_its_own_message():
    tree = silent("t", [CHAT, SEARCH] * REPEATED_ROUNDS)
    failed = tree.children[1].model_copy(
        update={"status": "error", "status_message": "source timed out"}
    )
    tree = tree.model_copy(update={"children": [tree.children[0], failed, *tree.children[2:]]})

    assert failure_fields(tree, "s2")["error_message"] == "source timed out"
