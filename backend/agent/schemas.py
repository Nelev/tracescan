"""Data contracts of the graph: what nodes put into state, the failure categories and the diagnosis."""

from typing import Literal, TypedDict, get_args

from pydantic import BaseModel, Field

from trace_store.models import TraceId

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


class Evidence(BaseModel):
    """One piece of evidence for a diagnosis: a span of a trace in the cluster."""

    trace_id: TraceId
    span_id: TraceId  # the same id shape as a trace id
    note: str = Field(min_length=1, description="What this span shows that supports the cause.")


class Diagnosis(BaseModel):
    """The diagnoser's answer for one cluster. Nodes keep it in state as a plain dict."""

    cluster_id: str
    category: FailureCategory
    root_cause: str = Field(
        min_length=1, description="The cause, not the symptom, in one or two sentences."
    )
    suggested_fix: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(min_length=1)
