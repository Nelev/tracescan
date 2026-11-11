"""cluster_failures: groups the collected failures. Embeddings and HDBSCAN, no LLM calls."""

import asyncio

from langgraph.runtime import Runtime

from agent.clustering import cluster_map, group_failures, isolated_clusters
from agent.context import TraceContext
from agent.state import TriageState
from trace_store.models import TraceSummary


def _cluster(summaries: list[TraceSummary], context: TraceContext) -> dict:
    grouping = group_failures(summaries, context.embedder)
    clusters = grouping.clusters + isolated_clusters(
        summaries, grouping.unclustered, first_index=len(grouping.clusters)
    )
    found = cluster_map(grouping, clusters)
    return {
        "clusters": clusters,
        "unclustered": grouping.unclustered,
        "cluster_map": found and found.model_dump(),
    }


async def cluster_failures(state: TriageState, runtime: Runtime[TraceContext]) -> dict:
    """Cluster failed traces; each isolated failure becomes a one-trace cluster of its own.

    `unclustered` keeps those trace ids too, so a run can still report how many there were.
    `cluster_map` is the failures projected to 3D for the run page (ids and coordinates only),
    or None for a run too small to embed.
    """
    summaries = [TraceSummary.model_validate(row) for row in state.get("failed_traces", [])]
    # Embedding and projecting are CPU-bound and synchronous, so keep them off the event loop.
    return await asyncio.to_thread(_cluster, summaries, runtime.context)
