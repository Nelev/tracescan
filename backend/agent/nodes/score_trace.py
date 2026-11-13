"""score_trace: one judge branch per trace, reached through Send with a TraceTask.

The simplest version: one attempt. It fetches the trace's tree and asks the judge (agent.judge)
whether the request failed; a failed verdict also gets what clustering reads of its blamed span
(`failure_fields`), and each healthy span the judge picked gets its text (`agent.chunks.step_text`).
Any error, from the fetch or the model, records the trace in
`judge_failures`, logged by exception type only, and the run goes on with the others. There is
no retry round: the judge's own re-ask is its only second call, within the trace budget.

Every run appends one `judge_usage` entry, failed or not, so the spend shows.
"""

import logging
from dataclasses import asdict

from langgraph.runtime import Runtime

from agent.chunks import step_key, step_text
from agent.context import TraceContext
from agent.judge import failure_fields, judge_trace
from agent.model_guard import Spent
from agent.schemas import TraceTask

logger = logging.getLogger(__name__)


async def score_trace(state: TraceTask, runtime: Runtime[TraceContext]) -> dict:
    """Judge one trace. A failure is recorded, not raised, so it cannot drop the others.

    `state` is the Send payload, not the graph state: LangGraph's node type fixes the name.
    """
    trace_id = state["trace"]["trace_id"]
    context = runtime.context
    run = Spent()
    try:
        tree = await context.traces.get_trace_tree(trace_id)
        verdict = await judge_trace(tree, context.judge_model or context.model, run)
    except Exception as exc:
        # Type name only: the message could carry span contents.
        logger.error("judging %s failed: %s", trace_id, type(exc).__name__)
        result: dict = {"judge_failures": [trace_id]}
    else:
        if verdict["failed"]:
            verdict |= failure_fields(tree, verdict["blamed_span_id"])
        # The text each healthy pick is embedded as, built here while the tree is in hand.
        verdict["healthy_spans"] = [
            {"span_id": span_id, **step_key(tree, span_id), "text": step_text(tree, span_id)}
            for span_id in verdict.pop("healthy_span_ids")
        ]
        result = {"verdicts": [verdict]}
    return {**result, "judge_usage": [{"trace_id": trace_id, **asdict(run)}]}
