"""
Per-call guard for the trace MCP server.

TraceGuard is FastMCP middleware around every tools/call. It does the two things that need
state across calls: a call budget and an audit log. What one call may ask for is validated
where its arguments are declared: TraceId and FailedTraceQuery in models.py, and the app
allowlist inside search_failed_traces in mcp_server.py.

The budget assumes one server process is one graph run, which holds because TraceClient
starts a fresh stdio subprocess per run; on a shared transport it would silently become
global. Rejected calls spend budget too.

Every call is logged to stderr (never stdout: stdio carries the protocol) with the tool, the
outcome and a short hash of the arguments. Outcomes: ok; error (the tool raised, which
includes argument validation and the app check); denied (budget spent). Raw arguments,
results and exception messages are never logged, because traces may hold clinical content
and a validation error repeats its input.

Known limit: FastMCP's own "Invalid arguments for tool" warning (logger fastmcp.server.server)
repeats the rejected input of a malformed id or query, and this guard does not touch that
logger. An agent that sends clinical text as an id would see it on stderr.

get_trace_tree and get_span take only ids; scoping them to the allowed apps is the reader's
job, and the Postgres reader does it.
"""

import hashlib
import json
import logging
from typing import Any

import mcp.types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

logger = logging.getLogger(__name__)


def _digest(arguments: dict[str, Any]) -> str:
    """Short stable hash of the arguments, so calls can be matched without logging them."""
    raw = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


class TraceGuard(Middleware):
    """Call budget and audit log for the trace tools."""

    def __init__(self, max_calls: int) -> None:
        self._max_calls = max_calls
        self._calls = 0

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool = context.message.name
        digest = _digest(context.message.arguments or {})
        self._calls += 1  # attempts count, so rejected calls spend budget too

        if self._calls > self._max_calls:
            logger.warning("tool call denied: tool=%s reason=budget args=%s", tool, digest)
            raise ToolError("call denied: call budget exhausted")

        try:
            result = await call_next(context)
        except Exception:
            logger.info("tool call error: tool=%s args=%s", tool, digest)
            raise
        logger.info("tool call ok: tool=%s args=%s", tool, digest)
        return result
