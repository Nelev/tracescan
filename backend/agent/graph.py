"""
TraceScan graph. collect_traces, cluster_failures and diagnose_cluster are real; the other
nodes are placeholders.

Flow (diagnose_cluster runs once per cluster, in parallel, through Send):
  collect_traces -> cluster_failures -> diagnose_cluster x N -> join_diagnoses
    -> reproduce_failure -> match_known_issues -> draft_proposals
    -> human_review -> apply_actions -> END

A transient model error leaves a cluster unfinished: join_diagnoses then sends it back to
diagnose_cluster, which checks the cluster's budget in `model_usage` before and after each run.

Conditional edges end the run early when no traces failed, when no clusters were
found, or when no proposal was approved. interrupt() comes later.
"""

import asyncio

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Send

from agent.const import MAX_PARALLEL_BRANCHES
from agent.context import TraceContext
from agent.embeddings import FastEmbedEmbedder
from agent.mcp_client import TraceClient
from agent.model import build_diagnoser_model
from agent.nodes.cluster_failures import cluster_failures
from agent.nodes.collect_traces import collect_traces
from agent.nodes.diagnose_cluster import diagnose_cluster
from agent.progress import ProgressTransformer
from agent.schemas import ClusterTask
from agent.state import TriageState


def join_diagnoses(state: TriageState) -> dict:
    """Barrier after each round of diagnose branches; the router after it may start another."""
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


def diagnose_sends(state: TriageState) -> list[Send]:
    """One diagnose branch per cluster that has neither a diagnosis nor a recorded failure.

    A branch sees only its payload, so each carries the cluster's `model_usage` entries: the
    budget the node checks before and after its run.
    """
    done = {d["cluster_id"] for d in state.get("diagnoses", [])}
    done |= set(state.get("diagnosis_failures", []))
    usage = state.get("model_usage", [])
    return [
        Send(
            "diagnose_cluster",
            ClusterTask(
                cluster=c,
                model_usage=[u for u in usage if u["cluster_id"] == c["cluster_id"]],
            ),
        )
        for c in state.get("clusters", [])
        if c["cluster_id"] not in done
    ]


def route_after_cluster(state: TriageState) -> list[Send] | str:
    """One parallel diagnose branch per cluster; no clusters (e.g. all noise): end the run."""
    return diagnose_sends(state) or END


def route_after_join(state: TriageState) -> list[Send] | str:
    """Run the diagnose branch again for each cluster a transient error left unfinished.

    The node leaves a cluster unfinished only while it has budget, and every run uses up at
    least one attempt, so the loop ends. Nothing left to diagnose: carry on.
    """
    return diagnose_sends(state) or "reproduce_failure"


def route_after_review(state: TriageState) -> str:
    """Nothing approved: end the run without calling apply_actions."""
    return "apply_actions" if "approve" in state.get("decisions", {}).values() else END


def build_graph(checkpointer: BaseCheckpointSaver | None = None, store: BaseStore | None = None):
    """Compile the graph. Invoke it with ainvoke(..., context=TraceContext(...)), see agent.context.

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
    g.add_conditional_edges(
        "join_diagnoses", route_after_join, ["diagnose_cluster", "reproduce_failure"]
    )
    g.add_edge("reproduce_failure", "match_known_issues")
    g.add_edge("match_known_issues", "draft_proposals")
    g.add_edge("draft_proposals", "human_review")
    g.add_conditional_edges("human_review", route_after_review, ["apply_actions", END])
    g.add_edge("apply_actions", END)

    # The cap and the progress transformer live on the graph, so every caller (API, demo, Studio,
    # resume) gets them. The transformer only matters to astream_events(version="v3") callers.
    return g.compile(
        checkpointer=checkpointer, store=store, transformers=[ProgressTransformer]
    ).with_config({"max_concurrency": MAX_PARALLEL_BRANCHES})


async def main() -> None:
    async with TraceClient() as traces:
        context = TraceContext(traces, FastEmbedEmbedder(), build_diagnoser_model())
        result = await build_graph().ainvoke({"target_app": "medas"}, context=context)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
