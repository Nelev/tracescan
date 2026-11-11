"""The trace judge: one structured-output call that says whether a trace failed its user.

It decides, for each trace in a run's window (nodes/score_trace.py), whether the trace failed:
the decision the removed heuristic scoring job used to make when spans were stored. `judge_trace` takes a tree the trace
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


def error_type(span: SpanNode) -> str | None:
    """What kind of error a span recorded: its `error.type` attribute, else `exception.type` on the
    span, then on its first exception event. The same places, in the same order, as the trace
    reader (trace_store/postgres_reader._EXCEPTION_TYPE): a step can fail without raising."""
    recorded = [span.attributes.get("error.type"), span.attributes.get("exception.type")]
    recorded += [(event.get("attributes") or {}).get("exception.type") for event in span.events]
    return next((str(found) for found in recorded if found), None)


def failure_fields(tree: SpanNode, blamed_span_id: str) -> dict:
    """What clustering reads of a failed trace, from its blamed span: the step's name, its error
    type and its status message (already truncated by the trace server). Names, no attributes."""
    span = next(span for _, span in walk(tree) if span.span_id == blamed_span_id)
    return {
        "failing_span_name": span.name,
        "error_type": error_type(span),
        "error_message": span.status_message,
    }


def failed_summary(trace: dict, verdict: dict) -> dict:
    """A failed trace as clustering reads it: its TraceSummary dict, failure fields from the
    verdict. The signature is the blamed step and its error type, or the step alone: names only,
    no message, and nothing every failure shares (an attribution would pull them together)."""
    step, error = verdict["failing_span_name"], verdict["error_type"]
    return {
        **trace,
        "failing_span_id": verdict["blamed_span_id"],
        "failing_span_name": step,
        "error_message": verdict["error_message"],
        "min_score": verdict["score"],
        "signature": f"{step} {error}" if error else step,
    }


def retry_message(blamed: str | None, valid: set[str]) -> str:
    """The correction sent back to the model: ids only, never span contents."""
    named = (
        f"The span you blamed, {blamed}, is not" if blamed else "You blamed no span, which is not"
    )
    return (
        f"{named} a span of the trace above. The request failed, so blame one of these span "
        f"ids: {', '.join(sorted(valid))}.\nAnswer again with every field."
    )


async def judge_trace(tree: SpanNode, model: BaseChatModel, run: Spent) -> dict:
    """Judge one trace; returns the verdict as a plain dict. Every call is added to `run`.

    The re-ask runs only while `run` is within the trace budget. A model error is raised for the
    caller to handle.
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
        and run.ok(trace_budget())
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
