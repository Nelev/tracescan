"""
Read-only FastMCP server over a TraceReader.

Exposes exactly three tools: search_traces, get_trace_tree, get_span.
Everything is sanitized here (trace_store/sanitize.py) so clinical text does not leave the MCP
boundary in bulk: span and event attributes outside an allowlist are redacted, and free text is
truncated.

Run over stdio with: uv run python -m trace_store.mcp_server
"""

import logging
import os
from collections.abc import Iterable

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from trace_store.const import (
    ALLOWED_APPS,
    MAX_ATTR_CHARS_SPAN,
    MAX_ATTR_CHARS_TREE,
    MAX_TOOL_CALLS,
)
from trace_store.guard import TraceGuard
from trace_store.models import SpanNode, TraceId, TraceQuery, TraceSummary
from trace_store.postgres_reader import PostgresTraceReader, read_only_engine
from trace_store.reader import TraceReader
from trace_store.sanitize import sanitize_span, sanitize_summary


def build_server(
    reader: TraceReader,
    *,
    allowed_apps: Iterable[str] = ALLOWED_APPS,
    max_calls: int = MAX_TOOL_CALLS,
) -> FastMCP:
    """Build the MCP server with its three read-only tools, all reading through `reader`.

    Any TraceReader works (Postgres in the app, a small one in tests); the server never touches the data store itself.
    Every tool call passes through TraceGuard (a budget of `max_calls` per server process, so per
    graph run, plus an audit log). search_traces serves only `allowed_apps`, and trace and
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
    async def search_traces(query: TraceQuery) -> list[TraceSummary]:
        """List every trace of an app, failed or not, newest first, as short summaries."""
        if query.app not in allowed:
            raise ToolError("app not allowed")
        return [sanitize_summary(s) for s in await reader.search_traces(query)]

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
    """Serve the traces stored in Postgres over stdio. Needs TRACE_DATABASE_URL."""
    # The guard's audit log goes to stderr; stdout belongs to the protocol.
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("trace_store.guard").setLevel(logging.INFO)
    url = os.environ.get("TRACE_DATABASE_URL")
    if not url:
        raise SystemExit("set TRACE_DATABASE_URL (a role that can read spans and scores)")
    build_server(PostgresTraceReader(read_only_engine(url))).run()


if __name__ == "__main__":
    main()
