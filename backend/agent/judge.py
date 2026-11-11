"""The trace judge: one structured-output call that says whether a trace failed its user.

It replaces nothing yet: it is the first piece of moving the decision "this trace failed" from the
heuristic scoring job (trace_store/scoring.py) into the agent. `judge_trace` takes a tree the trace
server already sanitized, so the model sees no attribute outside the allowlist.

The score is the model's; whether that counts as failed is the code's (`JUDGE_FAILED_MAX_SCORE`).
A failed trace must blame a span of the tree it was shown: if it does not, the model is asked once
more with the valid ids, and if it still names an unknown span, or none, the code blames the
deepest error span (the root when no span failed). A trace that did not fail blames nothing.
"""

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from agent.const import JUDGE_FAILED_MAX_SCORE
from agent.evidence import span_index, walk
from agent.model_guard import Spent, structured_asker, trace_budget
from agent.schemas import BlameCheck, TraceVerdict
from trace_store.models import SpanNode

JUDGE_PROMPT = (Path(__file__).parent / "judge_prompt.md").read_text()


def fallback_span(tree: SpanNode) -> str:
    """The deepest error span, the earliest of several; the root when no span failed.

    Deeper than the diagnoser's fallback (agent.evidence.fallback_evidence), which takes the
    first error top down: an error marks every span up to the root, so the deepest is the cause.
    """
    errors = [(depth, span) for depth, span in walk(tree) if span.status == "error"]
    if not errors:
        return tree.span_id
    return min(errors, key=lambda found: (-found[0], found[1].start_time))[1].span_id


def retry_message(blamed: str | None, valid: set[str]) -> str:
    """The correction sent back to the model: ids only, never span contents."""
    named = (
        f"The span you blamed, {blamed}, is not" if blamed else "You blamed no span, which is not"
    )
    return (
        f"{named} a span of the trace above. The request failed, so blame one of these span "
        f"ids: {', '.join(sorted(valid))}.\nAnswer again with every field."
    )


async def judge_trace(
    tree: SpanNode, model: BaseChatModel, run: Spent, before: Spent | None = None
) -> dict:
    """Judge one trace; returns the verdict as a plain dict. Every call is added to `run`.

    `before` is what earlier runs for this trace spent: the re-ask runs only while both together
    are within the trace budget, as diagnose_cluster checks a cluster's. A model error is raised
    for the caller to handle.
    """
    ask = structured_asker(model, TraceVerdict, run)
    messages: list[BaseMessage] = [
        SystemMessage(JUDGE_PROMPT),
        HumanMessage(tree.model_dump_json(exclude_defaults=True)),
    ]
    verdict = await ask(messages)
    valid = span_index([tree])[tree.trace_id]
    retried = False
    if (
        verdict.score <= JUDGE_FAILED_MAX_SCORE
        and verdict.blamed_span_id not in valid
        and ((before or Spent()) + run).ok(trace_budget())
    ):
        messages = [
            *messages,
            AIMessage(verdict.model_dump_json()),
            HumanMessage(retry_message(verdict.blamed_span_id, valid)),
        ]
        verdict = await ask(messages)
        retried = True
    # Decided once, on the last answer, which may have changed its mind about the failure.
    failed = verdict.score <= JUDGE_FAILED_MAX_SCORE
    blamed: str | None = None
    check: BlameCheck | None = None
    if failed:
        if verdict.blamed_span_id in valid:
            blamed, check = verdict.blamed_span_id, "corrected" if retried else "valid"
        else:
            blamed, check = fallback_span(tree), "fallback"
    return {
        "trace_id": tree.trace_id,
        "failed": failed,
        "score": verdict.score,
        "reason": verdict.reason,
        "blamed_span_id": blamed,
        "blame_check": check,
        # Only a failure has one; a failed trace the model did not attribute is unclear.
        "attribution": (verdict.attribution or "unclear") if failed else None,
    }
