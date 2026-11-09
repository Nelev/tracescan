"""
Read-only FastMCP server over a TraceReader.

Exposes exactly three tools: search_failed_traces, get_trace_tree, get_span.
Everything is sanitized here so clinical text does not leave the MCP boundary in bulk:
span and event attributes outside an allowlist are redacted, and free text is truncated.

Run over stdio with: uv run python -m trace_store.mcp_server
"""

import logging
from collections.abc import Iterable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from trace_store.const import (
    ALLOWED_APPS,
    MAX_ATTR_CHARS_SPAN,
    MAX_ATTR_CHARS_TREE,
    MAX_SUMMARY_CHARS,
    MAX_TOOL_CALLS,
    REDACTED,
    SAFE_ATTRIBUTE_KEYS,
    SAFE_ATTRIBUTE_PREFIXES,
    TRUNCATION_SUFFIX,
)
from trace_store.guard import TraceGuard
from trace_store.models import FailedTraceQuery, SpanNode, TraceId, TraceSummary
from trace_store.reader import FixtureTraceReader, TraceReader


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


def build_server(
    reader: TraceReader,
    *,
    allowed_apps: Iterable[str] = ALLOWED_APPS,
    max_calls: int = MAX_TOOL_CALLS,
) -> FastMCP:
    """Build the MCP server with its three read-only tools, all reading through `reader`.

    Any TraceReader works (fixture now, Postgres later); the server never touches the data store itself.
    Every tool call passes through TraceGuard (a budget of `max_calls` per server process, so per
    graph run, plus an audit log). search_failed_traces serves only `allowed_apps`, and trace and
    span ids must match TraceId.
    """
    mcp = FastMCP(
        "tracescan-traces",
        instructions="Read-only access to an LLM app's traces. Nothing here can modify data.",
    )
    mcp.add_middleware(TraceGuard(max_calls))
    allowed = frozenset(allowed_apps)
    read_only = {"readOnlyHint": True}

    # The docstrings below are sent to the agent as the tool descriptions, so they
    # describe the tool for the agent; the comments describe the code for us.

    @mcp.tool(annotations=read_only)
    async def search_failed_traces(query: FailedTraceQuery) -> list[TraceSummary]:
        """Find failed traces of an app, newest first, as short summaries."""
        if query.app not in allowed:
            raise ToolError("app not allowed")
        # Filtering, ordering and the row cap all live in the reader and in FailedTraceQuery.
        return [sanitize_summary(s) for s in await reader.search_failed_traces(query)]

    @mcp.tool(annotations=read_only)
    async def get_trace_tree(trace_id: TraceId) -> SpanNode:
        """Get a trace's full span tree. Long attribute values are truncated; use get_span for more."""
        # Whole tree in one call, so the tight truncation limit.
        root = await reader.get_trace_tree(trace_id)
        if root is None:
            raise ToolError(f"unknown trace_id: {trace_id}")
        return sanitize_span(root, MAX_ATTR_CHARS_TREE)

    @mcp.tool(annotations=read_only)
    async def get_span(trace_id: TraceId, span_id: TraceId) -> SpanNode:
        """Get one span with its attributes and events (no children)."""
        # One span, so a looser truncation limit; non-allowlisted attributes are still redacted.
        span = await reader.get_span(trace_id, span_id)
        if span is None:
            raise ToolError(f"unknown span: {trace_id}/{span_id}")
        return sanitize_span(span, MAX_ATTR_CHARS_SPAN)

    return mcp


def main() -> None:
    """Serve the fixture reader over stdio. The Postgres reader replaces it once the trace store exists."""
    # The guard's audit log goes to stderr; stdout belongs to the protocol.
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("trace_store.guard").setLevel(logging.INFO)
    build_server(FixtureTraceReader()).run()


if __name__ == "__main__":
    main()
