"""
TraceScan: simplest LangGraph structure, every node a placeholder.

Flow (linear):
  collect_traces -> cluster_failures -> diagnose_cluster -> join_diagnoses
    -> reproduce_failure -> match_known_issues -> draft_proposals
    -> human_review -> apply_actions -> END

Fan-out (Send), interrupt(), conditional edges and a checkpointer come later.
"""

from langgraph.graph import END, START, StateGraph

from agent.state import TriageState


def collect_traces(state: TriageState) -> dict:
    """Read failed traces for the target app (read-only MCP tools)."""
    return {"failed_traces": [{"trace_id": "t0"}]}


def cluster_failures(state: TriageState) -> dict:
    """Group failed traces (embeddings + HDBSCAN, no LLM)."""
    return {"clusters": [{"cluster_id": "c0", "trace_ids": ["t0"]}]}


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


def build_graph():
    g = StateGraph(TriageState)
    nodes = [
        collect_traces,
        cluster_failures,
        diagnose_cluster,
        join_diagnoses,
        reproduce_failure,
        match_known_issues,
        draft_proposals,
        human_review,
        apply_actions,
    ]
    for node in nodes:
        g.add_node(node.__name__, node)

    g.add_edge(START, nodes[0].__name__)
    for a, b in zip(nodes, nodes[1:]):
        g.add_edge(a.__name__, b.__name__)
    g.add_edge(nodes[-1].__name__, END)
    return g.compile()


if __name__ == "__main__":
    result = build_graph().invoke({"target_app": "medas"})
    for key, value in result.items():
        print(f"{key}: {value}")
