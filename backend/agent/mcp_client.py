"""
MCP client for the agent: the graph's only way to reach traces.

TraceClient starts trace_store.mcp_server as a stdio subprocess once and keeps
the session open, so many calls cost one server start:

    async with TraceClient() as traces:
        failed = await traces.search_failed_traces(FailedTraceQuery(app="medas"))

Open and close it in the same async task. It cannot span the human-review pause
(that ends the graph invocation), so it lives for one graph invocation. The server's
per-process call budget (trace_store/guard.py) relies on this: one session, one run.

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

from trace_store.models import FailedTraceQuery, SpanNode, TraceSummary

SERVER_NAME = "traces"
REQUEST_TIMEOUT = timedelta(seconds=30)  # so a hung server cannot hang the graph
# The stdio client passes the subprocess only a minimal environment; anything else the
# server needs must be added under "env".
TRACE_SERVER: StdioConnection = {
    "transport": "stdio",
    "command": sys.executable,
    "args": ["-m", "trace_store.mcp_server"],
    "cwd": Path(__file__).parent.parent,  # backend/, so trace_store is importable
    "session_kwargs": {"read_timeout_seconds": REQUEST_TIMEOUT},
}


class TraceClient:
    """One open session to the trace server. Use as an async context manager."""

    def __init__(self, database_url: str | None = None) -> None:
        # With a URL the server reads Postgres (trace_store/postgres_reader.py), else the fixture.
        self._server: StdioConnection = (
            {**TRACE_SERVER, "env": {"TRACE_DATABASE_URL": database_url}}
            if database_url
            else TRACE_SERVER
        )
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "TraceClient":
        client = MultiServerMCPClient({SERVER_NAME: self._server})
        self._session = await self._stack.enter_async_context(client.session(SERVER_NAME))
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()
        self._session = None

    def _open_session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("TraceClient must be used as an async context manager")
        return self._session

    async def _call(self, tool: str, arguments: dict) -> dict:
        """Call a server tool and return its structured result."""
        result = await self._open_session().call_tool(tool, arguments)
        if result.isError:
            raise RuntimeError(f"{tool} failed: {result.content}")
        if result.structuredContent is None:
            raise RuntimeError(f"{tool} returned no structured content: {result.content}")
        return result.structuredContent

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        """Failed traces matching the query, newest first."""
        args = {"query": query.model_dump(mode="json", exclude_none=True)}
        rows = (await self._call("search_failed_traces", args))["result"]
        return [TraceSummary.model_validate(row) for row in rows]

    async def get_trace_tree(self, trace_id: str) -> SpanNode:
        """One trace's span tree, redacted and truncated by the server."""
        return SpanNode.model_validate(await self._call("get_trace_tree", {"trace_id": trace_id}))
