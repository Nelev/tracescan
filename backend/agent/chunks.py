"""The text a span is embedded as, so a failed step can find healthy calls of the same step.

Pure: a sanitized span tree and a span id in, a few labelled lines out. Healthy and failed spans
use the same lines, so a failed span's text is the query. Numbers become words (`hits: none`,
not `0`) and only names, the status and the error type go in: no status message or other
attribute value, which can hold clinical text. Bump CHUNK_TEMPLATE_VERSION on any change here.
"""

from agent.const import HITS_BUCKETS, LATENCY_BUCKETS_S
from agent.judge import error_type
from trace_store.models import SpanNode


def bucket_word(value: float, buckets: tuple[tuple[float, str], ...]) -> str:
    """The word of the first bucket whose upper bound is above the value; the last one's."""
    return next((word for bound, word in buckets if value < bound), buckets[-1][1])


def _find(span: SpanNode, span_id: str, parent: SpanNode | None = None):
    if span.span_id == span_id:
        return span, parent
    for child in span.children:
        if found := _find(child, span_id, span):
            return found
    return None


def span_name(tree: SpanNode, span_id: str) -> str:
    """Raises KeyError for a span id that is not in the tree."""
    found = _find(tree, span_id)
    if found is None:
        raise KeyError(span_id)
    return found[0].name


def step_text(tree: SpanNode, span_id: str) -> str:
    """Raises KeyError for a span id that is not in the tree."""
    found = _find(tree, span_id)
    if found is None:
        raise KeyError(span_id)
    span, parent = found

    outcome = f"error {error_type(span) or 'of unknown type'}" if span.status == "error" else "ok"
    hits = span.attributes.get("retrieval.hits")
    if isinstance(hits, int):  # a redacted count is a string: left out
        outcome += f", hits: {bucket_word(hits, HITS_BUCKETS)}"

    siblings = sorted(parent.children, key=lambda s: s.start_time) if parent else [span]
    at = siblings.index(span)
    seconds = (span.end_time - span.start_time).total_seconds()
    return "\n".join(
        [
            f"step: {span.name}",
            f"outcome: {outcome}",
            f"previous: {siblings[at - 1].name if at > 0 else 'none'}",
            f"next: {siblings[at + 1].name if at + 1 < len(siblings) else 'none'}",
            f"inside: {parent.name if parent else 'none'}",
            f"latency: {bucket_word(seconds, LATENCY_BUCKETS_S)}",
        ]
    )
