"""
TraceDoctor: LangGraph schema sketch (LangGraph 1.x).

Flow:
  collect_traces -> cluster_failures
    -> [Send per cluster]  diagnose_cluster   -> join_diagnoses
    -> [Send per diagnosis] reproduce_failure -> match_known_issues
    -> draft_proposals -> human_review (interrupt) -> apply_actions -> END

Node bodies are stubs with fake data so the graph runs end to end.
Replace the TODOs with real Langfuse MCP calls, embeddings + HDBSCAN,
LLM structured output, and sandboxed replays.
"""

from __future__ import annotations

import operator
from collections import defaultdict
from typing import Annotated, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_store
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, Send, interrupt
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

FailureCategory = Literal[
    # single-agent categories
    "retrieval_miss", "tool_schema_error", "context_overflow",
    "prompt_regression", "model_quality", "infra_error",
    # MAST top-level categories (for multi-agent targets)
    "system_design", "inter_agent_misalignment", "task_verification",
    "unknown",
]


class TraceSummary(BaseModel):
    """Compact view of one failed trace, built from Langfuse data."""
    trace_id: str
    query: str
    failed_step: str            # name of the span/node where it went wrong
    error_type: str | None      # exception class, or None for "silent" failures
    score: float | None         # eval score if the trace was scored
    latency_ms: int


class Cluster(BaseModel):
    cluster_id: str
    signature: str              # short human-readable description of the group
    trace_ids: list[str]
    exemplars: list[TraceSummary]   # a few representative traces for the LLM


class Evidence(BaseModel):
    trace_id: str
    span: str
    note: str


class Diagnosis(BaseModel):
    """Structured output of the diagnoser LLM call."""
    cluster_id: str
    category: FailureCategory
    root_cause: str
    suggested_fix: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence]


class Reproduction(BaseModel):
    cluster_id: str
    attempts: int
    failures: int

    @property
    def status(self) -> Literal["confirmed", "flaky", "not_reproduced"]:
        if self.failures == self.attempts:
            return "confirmed"
        return "flaky" if self.failures > 0 else "not_reproduced"


class IssueProposal(BaseModel):
    cluster_id: str
    action: Literal["create_issue", "update_issue"]
    existing_issue: str | None = None
    title: str
    body: str
    regression_case: dict       # new item for the eval dataset


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class TriageState(TypedDict, total=False):
    # inputs
    target_app: str
    since: str                  # ISO timestamp for the triage window
    # pipeline data
    failed_traces: list[TraceSummary]
    clusters: list[Cluster]
    diagnoses: Annotated[list[Diagnosis], operator.add]          # fan-in reducer
    reproductions: Annotated[list[Reproduction], operator.add]   # fan-in reducer
    known_matches: dict[str, str]          # cluster_id -> existing issue id
    proposals: list[IssueProposal]
    decisions: dict[str, Literal["approve", "reject"]]
    actions_log: Annotated[list[str], operator.add]


class ClusterTask(TypedDict):
    """Private input for one parallel diagnose branch (sent via Send)."""
    target_app: str
    cluster: Cluster


class ReproTask(TypedDict):
    target_app: str
    cluster: Cluster
    diagnosis: Diagnosis


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def collect_traces(state: TriageState) -> dict:
    """READ tool. Pull failed / low-score traces via langfuse-mcp (--read-only)."""
    # TODO: call fetch_traces with filters (since, error level, score < threshold)
    fake = [
        TraceSummary(trace_id=f"t{i}", query=q, failed_step=s, error_type=e,
                     score=sc, latency_ms=900)
        for i, (q, s, e, sc) in enumerate([
            ("interaction warfarin + ibuprofen?", "retrieve", None, 0.1),
            ("interaction metformin + contrast?", "retrieve", None, 0.2),
            ("dose adjustment renal impairment", "call_tool:dosing", "ValidationError", None),
            ("dose for CrCl 25", "call_tool:dosing", "ValidationError", None),
            ("summarise 40-page discharge letter", "generate", "ContextLengthExceeded", None),
        ])
    ]
    return {"failed_traces": fake}


def cluster_failures(state: TriageState) -> dict:
    """Mostly code, not LLM. Real version: embed summaries + HDBSCAN."""
    groups: dict[tuple, list[TraceSummary]] = defaultdict(list)
    for t in state["failed_traces"]:
        groups[(t.failed_step, t.error_type)].append(t)
    clusters = [
        Cluster(cluster_id=f"c{i}", signature=f"{step} / {err or 'low score'}",
                trace_ids=[t.trace_id for t in ts], exemplars=ts[:3])
        for i, ((step, err), ts) in enumerate(groups.items())
    ]
    return {"clusters": clusters}


def fan_out_diagnosis(state: TriageState):
    if not state.get("clusters"):
        return END
    return [Send("diagnose_cluster", {"target_app": state["target_app"], "cluster": c})
            for c in state["clusters"]]


def diagnose_cluster(task: ClusterTask) -> dict:
    """LLM with structured output (Diagnosis), prompted with the failure taxonomy
    and the exemplar traces. Must cite spans as evidence."""
    # TODO: llm.with_structured_output(Diagnosis).invoke(prompt(task))
    c = task["cluster"]
    step = c.exemplars[0].failed_step
    category: FailureCategory = (
        "retrieval_miss" if step == "retrieve"
        else "tool_schema_error" if step.startswith("call_tool")
        else "context_overflow"
    )
    d = Diagnosis(
        cluster_id=c.cluster_id, category=category,
        root_cause=f"Stub root cause for {c.signature}",
        suggested_fix="Stub fix", confidence=0.7,
        evidence=[Evidence(trace_id=t.trace_id, span=t.failed_step, note="stub")
                  for t in c.exemplars],
    )
    return {"diagnoses": [d]}


def join_diagnoses(state: TriageState) -> dict:
    """Barrier node: runs once after all diagnose branches finish."""
    return {}


def fan_out_repro(state: TriageState):
    by_id = {c.cluster_id: c for c in state["clusters"]}
    return [Send("reproduce_failure", {"target_app": state["target_app"],
                                       "cluster": by_id[d.cluster_id], "diagnosis": d})
            for d in state["diagnoses"]]


def reproduce_failure(task: ReproTask) -> dict:
    """Replay exemplar inputs against the target app in a sandbox, N times each."""
    # TODO: call target app's API / run in container; compare against the failure
    attempts = 3
    failures = 3 if task["diagnosis"].category != "retrieval_miss" else 2
    return {"reproductions": [Reproduction(cluster_id=task["cluster"].cluster_id,
                                           attempts=attempts, failures=failures)]}


def match_known_issues(state: TriageState) -> dict:
    """Long-term memory: compare each cluster to issues seen in previous runs."""
    store = get_store()
    ns = ("known_issues", state["target_app"])
    matches = {}
    for c in state["clusters"]:
        # TODO: semantic search on the store (index embeddings) instead of exact key
        hit = store.get(ns, c.signature)
        if hit:
            matches[c.cluster_id] = hit.value["issue_id"]
    return {"known_matches": matches}


def draft_proposals(state: TriageState) -> dict:
    repro = {r.cluster_id: r for r in state["reproductions"]}
    clusters = {c.cluster_id: c for c in state["clusters"]}
    proposals = []
    for d in state["diagnoses"]:
        r = repro[d.cluster_id]
        if r.status == "not_reproduced":
            continue                    # don't file what we can't reproduce
        existing = state.get("known_matches", {}).get(d.cluster_id)
        c = clusters[d.cluster_id]
        proposals.append(IssueProposal(
            cluster_id=d.cluster_id,
            action="update_issue" if existing else "create_issue",
            existing_issue=existing,
            title=f"[{d.category}] {c.signature} ({len(c.trace_ids)} traces)",
            body=(f"Root cause: {d.root_cause}\nFix: {d.suggested_fix}\n"
                  f"Reproduction: {r.status} ({r.failures}/{r.attempts})\n"
                  f"Confidence: {d.confidence:.2f}"),
            regression_case={"input": c.exemplars[0].query,
                             "expect_not": d.category},
        ))
    return {"proposals": proposals}


def human_review(state: TriageState) -> dict:
    """Human-in-the-loop gate. Graph pauses here until resumed with decisions."""
    if not state["proposals"]:
        return {"decisions": {}}
    decisions = interrupt({
        "message": "Approve or reject each proposal",
        "proposals": [p.model_dump() for p in state["proposals"]],
    })
    return {"decisions": decisions}


def route_after_review(state: TriageState):
    approved = [v for v in state.get("decisions", {}).values() if v == "approve"]
    return "apply_actions" if approved else END


def apply_actions(state: TriageState, config: RunnableConfig) -> dict:
    """WRITE tools, only for approved proposals. dry_run writes markdown instead."""
    dry_run = config["configurable"].get("dry_run", True)
    store = get_store()
    ns = ("known_issues", state["target_app"])
    clusters = {c.cluster_id: c for c in state["clusters"]}
    log = []
    for p in state["proposals"]:
        if state["decisions"].get(p.cluster_id) != "approve":
            continue
        issue_id = p.existing_issue or f"ISSUE-{p.cluster_id}"
        # TODO: GitHub create/comment, append regression_case to Langfuse dataset
        log.append(f"{'[dry-run] ' if dry_run else ''}{p.action} {issue_id}: {p.title}")
        store.put(ns, clusters[p.cluster_id].signature, {"issue_id": issue_id})
    return {"actions_log": log}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_graph():
    g = StateGraph(TriageState)
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
    g.add_edge("collect_traces", "cluster_failures")
    g.add_conditional_edges("cluster_failures", fan_out_diagnosis,
                            ["diagnose_cluster", END])
    g.add_edge("diagnose_cluster", "join_diagnoses")
    g.add_conditional_edges("join_diagnoses", fan_out_repro, ["reproduce_failure"])
    g.add_edge("reproduce_failure", "match_known_issues")
    g.add_edge("match_known_issues", "draft_proposals")
    g.add_edge("draft_proposals", "human_review")
    g.add_conditional_edges("human_review", route_after_review,
                            ["apply_actions", END])
    g.add_edge("apply_actions", END)

    # Swap for PostgresSaver / PostgresStore in the deployed version
    return g.compile(checkpointer=InMemorySaver(), store=InMemoryStore())


# ---------------------------------------------------------------------------
# Demo run: pause at review, then resume with decisions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    graph = build_graph()
    cfg = {"configurable": {"thread_id": "triage-1", "dry_run": True}}

    result = graph.invoke({"target_app": "medas", "since": "2026-11-01T00:00:00Z"}, cfg)
    pending = result["__interrupt__"][0].value["proposals"]
    for p in pending:
        print("PROPOSAL:", p["title"])

    decisions = {p["cluster_id"]: "approve" for p in pending}
    decisions[pending[-1]["cluster_id"]] = "reject"     # reject one to show routing
    final = graph.invoke(Command(resume=decisions), cfg)
    for line in final["actions_log"]:
        print("ACTION:", line)
