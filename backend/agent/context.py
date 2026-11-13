"""
Run-scoped resources handed to the graph at invoke time, not at compile time.

The trace session lives for one invocation (see agent.mcp_client), so the compiled graph
must not hold it. Pass it per call:

    async with TraceClient(trace_database_url) as traces:
        await build_graph().ainvoke(input, context=TraceContext(traces, embedder, model))

The resume after the human review reads no traces (apply_actions works from the approved proposals
already in state), so it opens no session and passes `ClosedTraces()` instead.
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from langchain_core.language_models import BaseChatModel

from agent.actions import OUT_DIR
from agent.const import MAX_PARALLEL_DIAGNOSES
from agent.embeddings import Embedder
from agent.github import GitHubIssues
from agent.schemas import HealthyMatch, StepKey
from trace_store.models import SpanNode, TraceQuery, TraceSummary


class TraceAccess(Protocol):
    """The slice of TraceClient the nodes need, so tests can pass a fake."""

    async def search_traces(self, query: TraceQuery) -> list[TraceSummary]: ...

    async def get_trace_tree(self, trace_id: str) -> SpanNode: ...


class ClosedTraces:
    """Trace access for a run segment that must not read traces: every call fails."""

    async def search_traces(self, query: TraceQuery) -> list[TraceSummary]:
        raise RuntimeError("this run segment has no trace session")

    async def get_trace_tree(self, trace_id: str) -> SpanNode:
        raise RuntimeError("this run segment has no trace session")


class HealthyLookup(Protocol):
    """The slice of the healthy-span store (runs.healthy) the diagnoser reads."""

    async def similar(self, text: str, app: str, key: StepKey, k: int) -> list[HealthyMatch]: ...


@dataclass
class TraceContext:
    traces: TraceAccess
    embedder: Embedder  # required: the API passes one shared model, tests pass a HashingEmbedder
    model: BaseChatModel  # the diagnoser's chat model; tests pass a fake
    # The trace judge's model (agent.judge); None uses `model`. The app sets TRACE_JUDGE_MODEL's.
    judge_model: BaseChatModel | None = None
    # Healthy calls of a failing step, shown to the diagnoser next to the failure; None: none.
    healthy: HealthyLookup | None = None
    # Read by apply_actions only. The server sets these; nothing in a request can change them.
    dry_run: bool = True  # off opens GitHub issues, and needs `github`
    out_dir: Path = OUT_DIR  # where a dry run writes its files, and every run its regression cases
    github: GitHubIssues | None = None  # GITHUB_REPO and GITHUB_TOKEN; None: none set
    # Holds the diagnose branches to MAX_PARALLEL_DIAGNOSES while the judge branches use the
    # graph's wider max_concurrency. Not an init argument, so dataclasses.replace (what runs.Runs
    # does per run segment) makes a fresh one: the cap is per run, not per process.
    diagnose_slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(MAX_PARALLEL_DIAGNOSES), init=False, repr=False
    )
