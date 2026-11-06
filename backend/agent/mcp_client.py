"""
MCP client for the agent: the graph's only way to reach traces.

TraceClient starts trace_store.mcp_server as a stdio subprocess once and keeps
the session open, so many calls cost one server start:

    async with TraceClient() as traces:
        failed = await traces.search_failed_traces(FailedTraceQuery(app="medas"))

Open and close it in the same async task. It cannot span the human-review pause
(that ends the graph invocation), so it lives for one graph invocation.

The server command is a string on purpose: the agent package must not import
the server, the reader or any DB driver (see tests/test_boundaries.py).
"""

import sys
from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StdioConnection
from mcp import ClientSession

from trace_store.models import FailedTraceQuery, TraceSummary

SERVER_NAME = "traces"
CALL_TIMEOUT = timedelta(seconds=30)  # so a hung server cannot hang the graph
# The stdio client passes the subprocess only a minimal environment; anything the
# server needs later (e.g. the read-only DB URL) must be added under "env".
TRACE_SERVER: StdioConnection = {
    "transport": "stdio",
    "command": sys.executable,
    "args": ["-m", "trace_store.mcp_server"],
    "cwd": Path(__file__).parent.parent,  # backend/, so trace_store is importable
}


class TraceClient:
    """One open session to the trace server. Use as an async context manager."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "TraceClient":
        client = MultiServerMCPClient({SERVER_NAME: TRACE_SERVER})
        self._session = await self._stack.enter_async_context(client.session(SERVER_NAME))
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()
        self._session = None

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        """Failed traces matching the query, newest first."""
        if self._session is None:
            raise RuntimeError("TraceClient must be used as an async context manager")
        result = await self._session.call_tool(
            "search_failed_traces",
            {"query": query.model_dump(mode="json", exclude_none=True)},
            read_timeout_seconds=CALL_TIMEOUT,
        )
        if result.isError:
            raise RuntimeError(f"search_failed_traces failed: {result.content}")
        return [TraceSummary.model_validate(row) for row in result.structuredContent["result"]]
