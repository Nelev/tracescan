"""
Run-scoped resources handed to the graph at invoke time, not at compile time.

The trace session lives for one invocation (see agent.mcp_client), so the compiled graph
must not hold it. Pass it per call:

    async with TraceClient() as traces:
        await build_graph().ainvoke(input, context=TraceContext(traces, embedder, model))

The resume after the human review reads no traces (apply_actions works from the approved proposals
already in state), so it opens no session and passes `ClosedTraces()` instead.
"""

from dataclasses import dataclass
from typing import Protocol

from langchain_core.language_models import BaseChatModel

from agent.embeddings import Embedder
from trace_store.models import FailedTraceQuery, SpanNode, TraceSummary


class TraceAccess(Protocol):
    """The slice of TraceClient the nodes need, so tests can pass a fake."""

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]: ...

    async def get_trace_tree(self, trace_id: str) -> SpanNode: ...


class ClosedTraces:
    """Trace access for a run segment that must not read traces: every call fails."""

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        raise RuntimeError("this run segment has no trace session")

    async def get_trace_tree(self, trace_id: str) -> SpanNode:
        raise RuntimeError("this run segment has no trace session")


@dataclass
class TraceContext:
    traces: TraceAccess
    embedder: Embedder  # required: the API passes one shared model, tests pass a HashingEmbedder
    model: BaseChatModel  # the diagnoser's chat model; tests pass a fake
