"""Sanitizing span data before it leaves the trace store: the MCP server and the trace API.

Span and event attributes outside an allowlist are redacted and free text is truncated, so
clinical text does not leave in bulk.
"""

from typing import Any

from trace_store.const import (
    MAX_SUMMARY_CHARS,
    REDACTED,
    SAFE_ATTRIBUTE_KEYS,
    SAFE_ATTRIBUTE_PREFIXES,
    TRUNCATION_SUFFIX,
)
from trace_store.models import SpanNode, TraceSummary


def _truncate(text: str, max_chars: int) -> str:
    """Cut text to max_chars, marking the cut."""
    return text[:max_chars] + TRUNCATION_SUFFIX if len(text) > max_chars else text


def _sanitize_attrs(attrs: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Return a new attributes dict: keys outside the allowlist redacted, long strings cut.

    Allowlisted values (numbers, booleans, short strings) pass through unchanged.
    """
    sanitized = {}
    for key, value in attrs.items():
        if key not in SAFE_ATTRIBUTE_KEYS and not key.startswith(SAFE_ATTRIBUTE_PREFIXES):
            sanitized[key] = REDACTED
        elif isinstance(value, str):
            sanitized[key] = _truncate(value, max_chars)
        else:
            sanitized[key] = value
    return sanitized


def _sanitize_event(event: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Return a copy of one span event with its attributes sanitized.

    An event without an attributes dict is returned as is.
    """
    attrs = event.get("attributes")
    if not isinstance(attrs, dict):
        return event
    return {**event, "attributes": _sanitize_attrs(attrs, max_chars)}


def sanitize_span(span: SpanNode, max_chars: int) -> SpanNode:
    """Return a copy of the span (and its children) that is safe to hand to the agent.

    Sanitizes the attributes, events and status message of the span and, recursively,
    of every child. The status message is the diagnoser's evidence, so it is truncated,
    not redacted. The reader's own objects are never modified.
    """
    return span.model_copy(
        update={
            "status_message": span.status_message and _truncate(span.status_message, max_chars),
            "attributes": _sanitize_attrs(span.attributes, max_chars),
            "events": [_sanitize_event(e, max_chars) for e in span.events],
            "children": [sanitize_span(c, max_chars) for c in span.children],
        }
    )


def sanitize_summary(summary: TraceSummary) -> TraceSummary:
    """Return a copy of the summary with its free-text fields truncated.

    A backstop: the producer of a summary is expected to keep clinical text out of it.
    """
    return summary.model_copy(
        update={
            "error_message": summary.error_message
            and _truncate(summary.error_message, MAX_SUMMARY_CHARS),
            "signature": _truncate(summary.signature, MAX_SUMMARY_CHARS),
        }
    )
