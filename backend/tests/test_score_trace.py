"""score_trace against fake traces and a fake judge model, so no model is ever called."""

import json
from dataclasses import replace

import pytest
from langgraph.runtime import Runtime

from agent.chunks import step_text
from agent.context import ClosedTraces
from agent.judge import error_type, failure_fields
from agent.nodes.score_trace import score_trace
from agent.schemas import TraceTask, TraceVerdict
from tests.fakes import FakeApiError, FakeTraces, fake_context, span_tree, summary
from tests.fakes import scripted_model as scripted

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
FINE = TraceVerdict(reason="Every step worked.", score=0.9)


async def score(model, trees=None, judge_model=None) -> dict:
    traces = FakeTraces(trees={"t1": TREE}) if trees is None else trees
    context = replace(fake_context(traces, model), judge_model=judge_model)
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
        children=[
            span_tree(
                "t1", span_id="tool", parent_span_id="root", name="execute_tool lookup", status="ok"
            )
        ],
    )
    fine = FINE.model_copy(update={"healthy_span_ids": ["tool"]})
    (verdict,) = (await score(scripted(fine), trees=FakeTraces(trees={"t1": tree})))["verdicts"]
    assert verdict["healthy_spans"] == [
        {"span_id": "tool", "step": "execute_tool lookup", "text": step_text(tree, "tool")}
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
async def test_a_model_error_records_the_trace_as_failed_to_judge_with_its_spend():
    result = await score(scripted(FakeApiError(503)))
    assert result["judge_failures"] == ["t1"]
    assert "verdicts" not in result
    assert result["judge_usage"] == [{"trace_id": "t1", "calls": 1, "tokens": 0, "cost_usd": 0.0}]


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
