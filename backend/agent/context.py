"""
Run-scoped resources handed to the graph at invoke time, not at compile time.

The trace session lives for one invocation (see agent.mcp_client), so the compiled graph
must not hold it. Pass it per call, which also works again after a human-review resume:

    async with TraceClient() as traces:
        await build_graph().ainvoke(input, context=TraceContext(traces))
"""

from dataclasses import dataclass
from typing import Protocol

from trace_store.models import FailedTraceQuery, TraceSummary


class TraceSearch(Protocol):
    """The slice of TraceClient the nodes need, so tests can pass a fake."""

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]: ...


@dataclass
class TraceContext:
    traces: TraceSearch
