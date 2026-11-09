"""Data contracts of the graph: what nodes put into state and the failure categories."""

from typing import Literal, TypedDict, get_args

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


FailureCategory = Literal[
    # single-agent causes
    "retrieval_miss",
    "tool_schema_error",
    "context_overflow",
    "prompt_regression",
    "model_quality",
    "infra_error",
    # MAST top-level categories, for multi-agent targets
    "system_design",
    "inter_agent_misalignment",
    "task_verification",
    "unknown",
]

# Every category has a section in taxonomy.md; tests/test_taxonomy.py keeps the two in step.
FAILURE_CATEGORIES: tuple[str, ...] = get_args(FailureCategory)
