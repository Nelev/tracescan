"""Data contracts of the graph: what nodes put into state, the failure categories and the diagnosis."""

from typing import Literal, TypedDict, get_args

from pydantic import BaseModel, Field

from trace_store.models import TraceId

# hdbscan: a dense group found on embeddings. step_error: failures sharing a failing step and error.
# isolated: one isolated failure that fit no group, diagnosed on its own.
ClusterMethod = Literal["hdbscan", "step_error", "isolated"]

# What the reviewer answers per proposal. human_review is resumed with {cluster_id: Decision}.
Decision = Literal["approve", "reject"]


class Cluster(TypedDict):
    """One group of failed traces, as stored in state (a plain dict) and read by later nodes."""

    cluster_id: str  # c0, c1, ... ordered by size, stable for the same input
    trace_ids: list[str]
    # The most common "failing step: normalised error" among the cluster's traces.
    signature: str
    exemplar_trace_ids: list[str]  # the newest few traces, to look at first; a subset of trace_ids
    method: ClusterMethod


class ClusterTask(TypedDict):
    """Private input of one diagnose branch: its cluster, not the whole state."""

    cluster: Cluster


class TraceTask(TypedDict):
    """Private input of one judge branch (score_trace): its trace's summary, not the whole state."""

    trace: dict  # a TraceSummary as plain JSON, as collect_traces stores it


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


class SpanRef(BaseModel):
    """A span of a trace, by id only: it cannot carry text."""

    trace_id: TraceId
    span_id: TraceId  # the same id shape as a trace id


class Evidence(SpanRef):
    """One piece of evidence for a diagnosis: a span of a trace in the cluster."""

    note: str = Field(min_length=1, description="What this span shows that supports the cause.")


# How a diagnosis's evidence fared against the traces the diagnoser was shown: valid at the first
# answer, corrected by one retry, or unsupported (it still cited spans it was not shown, so those
# were dropped and the confidence capped). diagnose_cluster adds it to the stored dict; the model
# never fills it, which is why it is not a field of Diagnosis.
EvidenceCheck = Literal["valid", "corrected", "unsupported"]


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


class StoredDiagnosis(Diagnosis):
    """A diagnosis as diagnose_cluster stores it: the model's answer plus the code's evidence check."""

    evidence_check: EvidenceCheck


# How the failure embeddings were flattened to 3D for the cluster map: t-SNE, or PCA for few points.
Projection = Literal["tsne", "pca"]


class MapPoint(BaseModel):
    """One dot of the cluster map: traces with the same embedding that landed in the same cluster.

    Ids, coordinates and labels only, never the failure text it was embedded from.
    """

    trace_ids: list[str] = Field(min_length=1)  # sorted; more than one when embeddings coincide
    x: float  # each axis scaled into [-1, 1]
    y: float
    z: float
    cluster_id: str  # the final cluster, c0, c1, ...
    stage: ClusterMethod  # which clustering stage put the traces there
    hdbscan_label: int  # HDBSCAN's own label, -1 for noise (before the step-and-error pass)
    # HDBSCAN's membership strength, 0 to 1: 0 for noise, and for a member at its group's edge.
    membership: float


class ClusterMap(BaseModel):
    """The failed traces of a run in 3D, for the run page's cluster map.

    HDBSCAN ran on the full embeddings with cosine distance; this is a projection of them, so
    `trust` (scikit-learn's trustworthiness, 0 to 1) says how well near neighbours stayed near.
    """

    projection: Projection
    trust: float | None  # None when there are too few distinct points to measure it
    points: list[MapPoint]


# Whose fault a failure is. app: the application's prompts, tools, retrieval, limits or error
# handling (a provider error with no retry is app). external: a cause outside the application that
# it handled as well as it could. Not used to decide whether a trace failed: an outage still hurts
# users, so it is a label later steps can sort and filter on.
Attribution = Literal["app", "external", "unclear"]


class TraceVerdict(BaseModel):
    """The judge's answer for one trace: how well the request went, and the span to blame.

    agent.judge stores it as a plain dict with the trace id, `failed` (decided by the code from
    the score) and `blame_check`; the model fills none of those. Field order is answer order:
    the reason first, so the score and the attribution follow from it.
    """

    reason: str = Field(
        min_length=1, description="One or two sentences on why the request went well or badly."
    )
    score: float = Field(
        ge=0, le=1, description="0.0: the request failed its user. 1.0: it went fine."
    )
    blamed_span_id: str | None = Field(
        default=None,
        description="For a failed request, the span where the failure started; null otherwise.",
    )
    attribution: Attribution | None = Field(
        default=None,
        description=(
            "For a failed request: app if the cause is the application's own behaviour, "
            "including an outside error it did not handle well; external if the cause is "
            "outside it and it handled that as well as it reasonably could; unclear if the "
            "trace does not show which. Null for a request that went fine."
        ),
    )
    healthy_span_ids: list[str] = Field(
        default_factory=list,
        description=(
            "For a request that went fine: up to 3 model, tool or retrieval spans that did their "
            "work and whose result the request used. Empty for a failed request, or when unsure."
        ),
    )


# How a failed trace's blamed span fared against the tree the judge was shown: valid at the first
# answer, corrected by one retry, or fallback (the code picked the span). None for a trace that
# did not fail, like its blamed span and attribution.
BlameCheck = Literal["valid", "corrected", "fallback"]


class RegressionCase(BaseModel):
    """What the eval dataset keeps of a cluster: ids only, so no span text or input is copied.

    A later replay resolves the inputs from the trace store by id. The same shape is one JSONL
    line in a dry run and one row of a future regression-cases table.
    """

    cluster_id: str
    signature: str
    category: FailureCategory
    exemplar_trace_ids: list[str]
    failing_spans: list[SpanRef]  # the spans the diagnosis cites


class Proposal(BaseModel):
    """One draft for the reviewer: an issue and, when the cluster was diagnosed, a regression case.

    Nodes keep it in state as a plain dict. A cluster without a diagnosis still gets a proposal
    (`diagnosed` False, no regression case), so a failed cluster is never silently dropped.
    """

    cluster_id: str
    title: str
    body: str  # the issue, as markdown
    # How far the cause was checked. The MVP never replays a failure, so it is always
    # "unverified"; the reproducer will set confirmed, flaky or unconfirmed.
    verification: str = "unverified"
    diagnosed: bool
    regression_case: RegressionCase | None = None
