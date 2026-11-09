"""Checks what a diagnosis cites against the traces the diagnoser was shown.

The diagnoser sees only a cluster's exemplar traces, so a citation is real only if its span is in
one of those trees. These are pure functions; diagnose_cluster decides what to do about a bad one.
"""

from collections.abc import Iterable, Iterator, Sequence

from agent.schemas import Diagnosis, Evidence
from trace_store.models import SpanNode

SpanIndex = dict[str, set[str]]  # trace id -> the ids of its spans

FALLBACK_NOTE = (
    "Added by the evidence check: the model cited no span it was shown. "
    "This is the first failing span of an exemplar trace."
)


def _walk(span: SpanNode) -> Iterator[SpanNode]:
    yield span
    for child in span.children:
        yield from _walk(child)


def span_index(trees: Iterable[SpanNode]) -> SpanIndex:
    return {tree.trace_id: {span.span_id for span in _walk(tree)} for tree in trees}


def _is_real(evidence: Evidence, index: SpanIndex) -> bool:
    # A span counts only under its own trace.
    return evidence.span_id in index.get(evidence.trace_id, set())


def invalid_citations(diagnosis: Diagnosis, index: SpanIndex) -> list[Evidence]:
    return [e for e in diagnosis.evidence if not _is_real(e, index)]


def keep_valid(diagnosis: Diagnosis, index: SpanIndex) -> list[Evidence]:
    return [e for e in diagnosis.evidence if _is_real(e, index)]


def retry_message(bad: Sequence[Evidence], index: SpanIndex) -> str:
    """The correction sent back to the model: ids only, never span contents."""
    rejected = ", ".join(f"{e.trace_id}/{e.span_id}" for e in bad)
    shown = "\n".join(f"{trace_id}: {', '.join(sorted(s))}" for trace_id, s in index.items())
    return (
        f"These citations are not spans of the traces above, so they were rejected: {rejected}.\n"
        f"Cite only these spans (trace id: span ids):\n{shown}\n"
        "Answer again with every field of the diagnosis, citing only the spans listed."
    )


def fallback_evidence(trees: Sequence[SpanNode]) -> list[Evidence]:
    """The first failing span of each tree, or its root when no span failed."""
    return [
        Evidence(
            trace_id=tree.trace_id,
            span_id=next((s for s in _walk(tree) if s.status == "error"), tree).span_id,
            note=FALLBACK_NOTE,
        )
        for tree in trees
    ]
