from typing import Literal, Required, TypedDict

# hdbscan: a dense group found on embeddings. step_error: failures sharing a failing step and error.
ClusterMethod = Literal["hdbscan", "step_error"]


class Cluster(TypedDict):
    """One group of failed traces, as stored in state (a plain dict) and read by later nodes."""

    cluster_id: str  # c0, c1, ... ordered by size, stable for the same input
    trace_ids: list[str]
    # The most common "failing step: normalised error" among the cluster's traces.
    signature: str
    exemplar_trace_ids: list[str]  # the newest few traces, to look at first; a subset of trace_ids
    method: ClusterMethod


class TriageState(TypedDict, total=False):
    target_app: Required[str]
    since: str  # ISO 8601 with timezone, inclusive; optional
    until: str  # ISO 8601 with timezone, exclusive; optional
    failed_traces: list[dict]
    clusters: list[Cluster]
    # Trace ids that fit no cluster, even after regrouping the noise. Kept, but not diagnosed.
    unclustered: list[str]
    diagnoses: list[dict]
    reproductions: list[dict]
    known_matches: dict[str, str]
    proposals: list[dict]
    decisions: dict[str, str]
    actions_log: list[str]
