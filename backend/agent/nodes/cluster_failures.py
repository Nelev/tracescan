"""cluster_failures: groups the collected failures. Embeddings and HDBSCAN, no LLM calls."""

import asyncio

from langgraph.runtime import Runtime

from agent.clustering import cluster_summaries, isolated_clusters
from agent.context import TraceContext
from agent.state import TriageState
from trace_store.models import TraceSummary


async def cluster_failures(state: TriageState, runtime: Runtime[TraceContext]) -> dict:
    """Cluster failed traces; each isolated failure becomes a one-trace cluster of its own.

    `unclustered` keeps those trace ids too, so a run can still report how many there were.
    """
    summaries = [TraceSummary.model_validate(row) for row in state.get("failed_traces", [])]
    # Embedding is CPU-bound and synchronous, so keep it off the event loop.
    clusters, unclustered = await asyncio.to_thread(
        cluster_summaries, summaries, runtime.context.embedder
    )
    clusters += isolated_clusters(summaries, unclustered, first_index=len(clusters))
    return {"clusters": clusters, "unclustered": unclustered}
