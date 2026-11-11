import operator
from typing import Annotated, Required, TypedDict

from agent.schemas import Cluster, Decision


class TriageState(TypedDict, total=False):
    target_app: Required[str]
    since: str  # ISO 8601 with timezone, inclusive; optional
    until: str  # ISO 8601 with timezone, exclusive; optional
    # Every trace in the window (TraceSummary dicts), for the trace judge to decide which failed.
    traces: list[dict]
    # Appended to by the parallel judge branches, one verdict per judged trace (agent.judge).
    verdicts: Annotated[list[dict], operator.add]
    # Ids of traces whose judging failed. Kept, never dropped, so the run can report them.
    judge_failures: Annotated[list[str], operator.add]
    # One entry per judge run, failed or not: {trace_id, calls, tokens, cost_usd}. Numbers only,
    # kept apart from `model_usage` so every reader of that list can rely on a cluster id.
    judge_usage: Annotated[list[dict], operator.add]
    failed_traces: list[dict]
    clusters: list[Cluster]
    # Trace ids that fit no cluster, even after regrouping the noise. Kept, but not diagnosed.
    unclustered: list[str]
    # Appended to by the parallel diagnose branches, one entry per diagnosed cluster.
    diagnoses: Annotated[list[dict], operator.add]
    # Ids of clusters whose diagnosis failed. Kept, never dropped, so the run can report them.
    diagnosis_failures: Annotated[list[str], operator.add]
    # One entry per diagnose run, failed or not: {cluster_id, calls, tokens, cost_usd}. Numbers
    # only. A cluster's spend is the sum of its entries (agent.model_guard.spent_for).
    model_usage: Annotated[list[dict], operator.add]
    reproductions: list[dict]
    known_matches: dict[str, str]
    # One Proposal (agent.schemas) per cluster, in cluster order, written by draft_proposals.
    proposals: list[dict]
    decisions: dict[str, Decision]  # by cluster id, set when human_review is resumed
    actions_log: list[str]
