"""The trace judge: one structured-output call that says whether a trace failed its user.

It decides, for each trace in a run's window (nodes/score_trace.py), whether the trace failed:
the decision the removed heuristic scoring job used to make when spans were stored. `judge_trace` takes a tree the trace
server already sanitized, so the model sees no attribute outside the allowlist.

The score is the model's; whether that counts as failed is the code's (`trace_store.models.is_failed`,
the same threshold the trace browser reads the stored score with).
A failed trace must blame a span of the tree it was shown: if it does not, the model is asked once
more with the valid ids, and if it still names an unknown span, or none, or the re-ask fails, the
code blames the deepest error span (the root when no span failed). A trace that did not fail
blames nothing.

A trace that went fine may name healthy spans, steps that worked, for the planned healthy-span
store; `healthy_picks` keeps the ones that hold up, from a clearly fine, clean trace only (`clean`):
no exception does not mean a right answer.
"""

import json
import logging
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from agent.const import (
    HEALTHY_MIN_SCORE,
    MAX_HEALTHY_PICKS,
    OFF_FORMAT_REPLIES,
    REPEATED_ROUNDS,
    REPLY_FORMAT,
    SYMPTOM_EMPTY,
    SYMPTOM_REPEATED,
    SYMPTOM_REPLY,
)
from agent.evidence import error_spans, span_index, walk
from agent.model_guard import Spent, retrying, structured_asker, trace_budget
from agent.schemas import BlameCheck, TraceVerdict
from trace_store.models import SpanNode, is_failed

logger = logging.getLogger(__name__)

JUDGE_PROMPT = (Path(__file__).parent / "judge_prompt.md").read_text()


def fallback_span(tree: SpanNode) -> str:
    """The deepest error span, the earliest of several; the root when no span failed.

    Deeper than the diagnoser's fallback (agent.evidence.fallback_evidence), which takes the
    first error top down: an error marks every span up to the root, so the deepest is the cause.
    """
    errors = list(error_spans(tree))
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


def rounds_per_tool(tree: SpanNode) -> dict[str, int]:
    """For each tool, how many rounds asked for it: a round is what happens after one model
    call (`chat` span), in time order, so several calls made together count once."""
    rounds: dict[str, set[int]] = {}
    round_number = 0
    for span in sorted((span for _, span in walk(tree)), key=lambda s: s.start_time):
        operation = span.attributes.get("gen_ai.operation.name")
        if operation == "chat" or span.name.startswith("chat "):
            round_number += 1
        elif operation == "execute_tool" or span.name.startswith("execute_tool "):
            rounds.setdefault(span.name, set()).add(round_number)
    return {tool: len(numbers) for tool, numbers in rounds.items()}


def symptom(tree: SpanNode, blamed: SpanNode) -> str | None:
    """What the trace shows of a failure whose blamed step recorded no error, in fixed words:
    a search that found nothing, a tool asked for round after round (REPEATED_ROUNDS), a reply
    not in the asked-for shape, else None. Read from the structure only, never a value."""

    def empty(span: SpanNode) -> bool:
        return span.attributes.get("retrieval.hits") == 0

    if any(empty(span) for _, span in walk(blamed)):
        return SYMPTOM_EMPTY
    if max(rounds_per_tool(tree).values(), default=0) >= REPEATED_ROUNDS:
        return SYMPTOM_REPEATED
    if tree.attributes.get(REPLY_FORMAT) in OFF_FORMAT_REPLIES:
        return SYMPTOM_REPLY
    if any(empty(span) for _, span in walk(tree)):
        return SYMPTOM_EMPTY
    return None


def failure_fields(tree: SpanNode, blamed_span_id: str) -> dict:
    """What clustering reads of a failed trace, from its blamed span: the step's name, its error
    type and its status message (already truncated by the trace server). Names, no attributes.

    A blamed step that recorded neither an error type nor a message gets its `symptom` as the
    message, so silent failures of different kinds are told apart, not all read as the step.
    """
    span = next(span for _, span in walk(tree) if span.span_id == blamed_span_id)
    kind = error_type(span)
    message = span.status_message
    if kind is None and not message:
        message = symptom(tree, span)
    return {"failing_span_name": span.name, "error_type": kind, "error_message": message}


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


def clean(tree: SpanNode) -> bool:
    """Nothing in the trace hints that it went wrong: no error span (a retried or reported
    failure is not a clean example) and no retrieval that found nothing (an answer with no
    records behind it raises no error). Proxies only: the judge never sees the answer.
    One pass, stopping at the first span that rules the trace out."""
    return not any(
        span.status == "error" or span.attributes.get("retrieval.hits") == 0
        for _, span in walk(tree)
    )


def healthy_picks(tree: SpanNode, valid: set[str], picked: list[str], score: float) -> list[str]:
    """The judge's healthy picks that become references. A pick is a candidate: none is kept
    unless the score is clear and the trace is clean; then spans of the tree (`valid`, its span
    ids, which judge_trace already has), not the root, each once, the first MAX_HEALTHY_PICKS.
    A bad pick is dropped, never asked about again."""
    if score < HEALTHY_MIN_SCORE or not clean(tree):
        return []
    ok = valid - {tree.span_id}
    return [span_id for span_id in dict.fromkeys(picked) if span_id in ok][:MAX_HEALTHY_PICKS]


# The same on every span of a trace: the models read them once, on the root.
_TRACE_WIDE = ("app_version", "schema_url")


def prompt_json(tree: SpanNode) -> str:
    """The tree as the judge and the diagnoser read it: compact JSON without default fields,
    and the app version and schema URL on the root only."""

    def strip(span: dict, root: bool) -> dict:
        if not root:
            for key in _TRACE_WIDE:
                span.pop(key, None)
        for child in span.get("children", []):
            strip(child, root=False)
        return span

    dumped = strip(tree.model_dump(mode="json", exclude_defaults=True), root=True)
    return json.dumps(dumped, ensure_ascii=False, separators=(",", ":"))


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

    A transient model error (throttling, a timeout, a server error) is retried call by call after
    a doubling wait, and the re-ask runs, only while `run` is within the trace budget: up to
    MAX_MODEL_ATTEMPTS calls in all. Any other error, or one with no budget left, is raised for
    the caller to handle, except on the re-ask: then the first verdict is kept, with the fallback
    blame.
    """
    ask = retrying(
        structured_asker(model, TraceVerdict, run), run, trace_budget(), f"judge of {tree.trace_id}"
    )
    messages: list[BaseMessage] = [
        SystemMessage(JUDGE_PROMPT),
        HumanMessage(prompt_json(tree)),
    ]
    verdict = await ask(messages)
    valid = span_index([tree])[tree.trace_id]
    retried = False
    if is_failed(verdict.score) and verdict.blamed_span_id not in valid and run.ok(trace_budget()):
        messages = [
            *messages,
            AIMessage(verdict.model_dump_json()),
            HumanMessage(retry_message(verdict.blamed_span_id, valid)),
        ]
        try:
            verdict = await ask(messages)
            retried = True
        except Exception as exc:
            # The first verdict is paid for: keep it, with the fallback blame below.
            logger.warning(
                "judge of %s: re-ask failed: %s, keeping the first answer",
                tree.trace_id,
                type(exc).__name__,
            )
    # Decided once, on the last answer, which may have changed its mind about the failure.
    failed = is_failed(verdict.score)
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
        # Only a trace that clearly went fine has examples of steps working.
        "healthy_span_ids": healthy_picks(tree, valid, verdict.healthy_span_ids, verdict.score),
    }
