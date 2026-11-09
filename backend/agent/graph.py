"""
TraceScan: simplest LangGraph structure, every node a placeholder.

Flow (linear):
  collect_traces -> cluster_failures -> diagnose_cluster -> join_diagnoses
    -> reproduce_failure -> match_known_issues -> draft_proposals
    -> human_review -> apply_actions -> END

Conditional edges end the run early when no traces failed, when no clusters were
found, or when no proposal was approved. collect_traces and cluster_failures are real; the
other nodes are placeholders. Fan-out (Send) and interrupt() come later.
"""

import asyncio

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from agent.context import TraceContext
from agent.embeddings import FastEmbedEmbedder
from agent.mcp_client import TraceClient
from agent.nodes.cluster_failures import cluster_failures
from agent.nodes.collect_traces import collect_traces
from agent.state import TriageState


def diagnose_cluster(state: TriageState) -> dict:
    """Diagnose each cluster, citing trace ids and spans as evidence."""
    return {"diagnoses": [{"cluster_id": "c0", "category": "unknown"}]}


def join_diagnoses(state: TriageState) -> dict:
    """Barrier after the diagnose branches."""
    return {}


def reproduce_failure(state: TriageState) -> dict:
    """Replay exemplar inputs against the target app."""
    return {"reproductions": [{"cluster_id": "c0", "status": "unverified"}]}


def match_known_issues(state: TriageState) -> dict:
    """Compare clusters with issues seen in earlier runs."""
    return {"known_matches": {}}


def draft_proposals(state: TriageState) -> dict:
    """Draft a GitHub issue and regression test per cluster."""
    return {"proposals": [{"cluster_id": "c0", "title": "placeholder issue"}]}


def human_review(state: TriageState) -> dict:
    """Human approves or rejects each proposal."""
    return {"decisions": {"c0": "approve"}}


def apply_actions(state: TriageState) -> dict:
    """Write issues and regression cases, only for approved proposals."""
    return {"actions_log": ["[dry-run] create_issue c0"]}


def route_after_collect(state: TriageState) -> str:
    """Nothing failed in the window: end the run."""
    return "cluster_failures" if state.get("failed_traces") else END


def route_after_cluster(state: TriageState) -> str:
    """No clusters (e.g. all noise): end the run."""
    return "diagnose_cluster" if state.get("clusters") else END


def route_after_review(state: TriageState) -> str:
    """Nothing approved: end the run without calling apply_actions."""
    return "apply_actions" if "approve" in state.get("decisions", {}).values() else END


def build_graph(checkpointer: BaseCheckpointSaver | None = None, store: BaseStore | None = None):
    """Compile the graph. Invoke it with ainvoke(..., context=TraceContext(traces, embedder)).

    With a checkpointer, every invoke needs a thread_id in its config.
    """
    g = StateGraph(TriageState, context_schema=TraceContext)

    g.add_node("collect_traces", collect_traces)
    g.add_node("cluster_failures", cluster_failures)
    g.add_node("diagnose_cluster", diagnose_cluster)
    g.add_node("join_diagnoses", join_diagnoses)
    g.add_node("reproduce_failure", reproduce_failure)
    g.add_node("match_known_issues", match_known_issues)
    g.add_node("draft_proposals", draft_proposals)
    g.add_node("human_review", human_review)
    g.add_node("apply_actions", apply_actions)

    g.add_edge(START, "collect_traces")
    g.add_conditional_edges("collect_traces", route_after_collect, ["cluster_failures", END])
    g.add_conditional_edges("cluster_failures", route_after_cluster, ["diagnose_cluster", END])
    g.add_edge("diagnose_cluster", "join_diagnoses")
    g.add_edge("join_diagnoses", "reproduce_failure")
    g.add_edge("reproduce_failure", "match_known_issues")
    g.add_edge("match_known_issues", "draft_proposals")
    g.add_edge("draft_proposals", "human_review")
    g.add_conditional_edges("human_review", route_after_review, ["apply_actions", END])
    g.add_edge("apply_actions", END)

    return g.compile(checkpointer=checkpointer, store=store)


async def main() -> None:
    async with TraceClient() as traces:
        context = TraceContext(traces, FastEmbedEmbedder())
        result = await build_graph().ainvoke({"target_app": "medas"}, context=context)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
