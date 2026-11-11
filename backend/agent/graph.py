"""
TraceScan graph. collect_traces, score_trace, cluster_failures, diagnose_cluster and
draft_proposals are real, human_review pauses the run with interrupt(), and apply_actions writes
the approved proposals as a dry run; reproduce_failure and match_known_issues are placeholders.

Flow (score_trace runs once per trace and diagnose_cluster once per cluster, in parallel,
through Send):
  collect_traces -> score_trace x T -> join_scores -> cluster_failures
    -> diagnose_cluster x N -> join_diagnoses
    -> reproduce_failure -> match_known_issues -> draft_proposals
    -> human_review -> apply_actions -> END

The trace judge (score_trace) decides which traces failed; join_scores turns its failed verdicts
into `failed_traces` for clustering.

A transient model error leaves a cluster unfinished: join_diagnoses then sends it back to
diagnose_cluster, which checks the cluster's budget in `model_usage` before and after each run.

Conditional edges end the run early when the window has no traces, when none failed, when no
clusters were found, or when no proposal was approved.

human_review pauses the run. Resume it on the same thread_id with
Command(resume={cluster_id: "approve" | "reject"}); that needs a checkpointer. Without one the
first invoke still returns at the pause, with `__interrupt__` in its result.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Send, interrupt

from agent.const import MAX_PARALLEL_BRANCHES
from agent.context import TraceContext
from agent.judge import failed_summary
from agent.nodes.apply_actions import apply_actions
from agent.nodes.cluster_failures import cluster_failures
from agent.nodes.collect_traces import collect_traces
from agent.nodes.diagnose_cluster import diagnose_cluster
from agent.nodes.draft_proposals import draft_proposals
from agent.nodes.score_trace import score_trace
from agent.progress import ProgressTransformer
from agent.schemas import ClusterTask, TraceTask
from agent.state import TriageState


def join_scores(state: TriageState) -> dict:
    """Barrier after the judge branches: the failed traces, newest first, as clustering reads them.

    A trace whose judging failed has no verdict, so it is not among them (it is in
    `judge_failures`).
    """
    verdicts = {v["trace_id"]: v for v in state.get("verdicts", [])}
    failed = [
        failed_summary(trace, verdicts[trace["trace_id"]])
        for trace in state.get("traces", [])
        if verdicts.get(trace["trace_id"], {}).get("failed")
    ]
    return {"failed_traces": failed}


def join_diagnoses(state: TriageState) -> dict:
    """Barrier after each round of diagnose branches; the router after it may start another."""
    return {}


def reproduce_failure(state: TriageState) -> dict:
    """Replay exemplar inputs against the target app."""
    return {"reproductions": [{"cluster_id": "c0", "status": "unverified"}]}


def match_known_issues(state: TriageState) -> dict:
    """Compare clusters with issues seen in earlier runs."""
    return {"known_matches": {}}


def human_review(state: TriageState) -> dict:
    """Pause until the reviewer has approved or rejected each proposal.

    The interrupt value is saved in the checkpoint and reaches the stream, so it holds ids only.
    The resume value is {cluster_id: Decision}, one per id asked here; whoever resumes checks it
    against this value (runs.Runs.review does).
    """
    cluster_ids = [p["cluster_id"] for p in state.get("proposals", [])]
    return {"decisions": interrupt({"cluster_ids": cluster_ids})}


def route_after_collect(state: TriageState) -> list[Send] | str:
    """One parallel judge branch per trace; no traces in the window: end the run."""
    return [Send("score_trace", TraceTask(trace=t)) for t in state.get("traces", [])] or END


def route_after_scores(state: TriageState) -> str:
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
    g.add_node("score_trace", score_trace)
    g.add_node("join_scores", join_scores)
    g.add_node("cluster_failures", cluster_failures)
    g.add_node("diagnose_cluster", diagnose_cluster)
    g.add_node("join_diagnoses", join_diagnoses)
    g.add_node("reproduce_failure", reproduce_failure)
    g.add_node("match_known_issues", match_known_issues)
    g.add_node("draft_proposals", draft_proposals)
    g.add_node("human_review", human_review)
    g.add_node("apply_actions", apply_actions)

    g.add_edge(START, "collect_traces")
    g.add_conditional_edges("collect_traces", route_after_collect, ["score_trace", END])
    g.add_edge("score_trace", "join_scores")
    g.add_conditional_edges("join_scores", route_after_scores, ["cluster_failures", END])
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

    # The cap and the progress transformer live on the graph, so every caller (API, eval, resume)
    # gets them. The transformer only matters to astream_events(version="v3") callers.
    return g.compile(
        checkpointer=checkpointer, store=store, transformers=[ProgressTransformer]
    ).with_config({"max_concurrency": MAX_PARALLEL_BRANCHES})
