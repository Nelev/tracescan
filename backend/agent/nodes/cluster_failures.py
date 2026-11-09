"""cluster_failures: groups the collected failures. Embeddings and HDBSCAN, no LLM calls."""

import asyncio

from langgraph.runtime import Runtime

from agent.clustering import cluster_summaries
from agent.context import TraceContext
from agent.state import TriageState
from trace_store.models import TraceSummary


async def cluster_failures(state: TriageState, runtime: Runtime[TraceContext]) -> dict:
    """Cluster failed traces; isolated failures go to `unclustered` instead of being dropped."""
    summaries = [TraceSummary.model_validate(row) for row in state.get("failed_traces", [])]
    # Embedding is CPU-bound and synchronous, so keep it off the event loop.
    clusters, unclustered = await asyncio.to_thread(
        cluster_summaries, summaries, runtime.context.embedder
    )
    return {"clusters": clusters, "unclustered": unclustered}
