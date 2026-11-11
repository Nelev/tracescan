"""Contracts for the trace-reading MCP tools (search_traces, get_trace_tree, get_span)."""

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

from trace_store.const import FAILED_MAX_SCORE, ID_PATTERN, MAX_LIMIT

SpanStatus = Literal["unset", "ok", "error"]
# A trace or span id taken as a tool argument. Pydantic rejects other shapes before the tool
# runs, and the pattern is part of the tool's JSON schema.
TraceId = Annotated[str, Field(pattern=ID_PATTERN)]


class TraceQuery(BaseModel):
    """Input of search_traces: every trace of an app in a window, failed or not.

    The agent's trace judge decides which ones failed, so nothing here reads scores.
    """

    app: str
    since: AwareDatetime | None = None  # inclusive
    until: AwareDatetime | None = None  # exclusive
    limit: int = Field(default=50, ge=1, le=MAX_LIMIT)


class TraceSummary(BaseModel):
    """One row from search_traces; a failed trace's gets its failure fields from the trace judge
    (agent.judge.failed_summary). Small enough to cluster without fetching trees."""

    trace_id: str
    app: str
    start_time: AwareDatetime
    duration_ms: float
    status: SpanStatus
    error_message: str | None = None
    failing_span_id: str | None = None
    failing_span_name: str | None = None
    min_score: float | None = None
    # Short text used for embedding. The producer keeps clinical content out; the MCP server truncates it.
    signature: str


class SpanNode(BaseModel):
    """One span in get_trace_tree / get_span. `children` is empty for get_span."""

    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    name: str
    kind: str = "internal"
    start_time: AwareDatetime
    end_time: AwareDatetime
    status: SpanStatus = "unset"
    status_message: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    children: list["SpanNode"] = Field(default_factory=list)


class TraceRow(BaseModel):
    """One trace in list_traces, failed or not: its root span, its spans and its lowest score.

    The failing fields are set for a failed trace only; like a TraceSummary, they are names,
    never a message or an attribute value.
    """

    trace_id: str
    start_time: AwareDatetime
    duration_ms: float
    status: SpanStatus  # the root span's
    spans: int
    min_score: float | None = None  # None: not scored yet
    failed: bool = False  # min_score <= FAILED_MAX_SCORE
    failing_span_id: str | None = None
    failing_span_name: str | None = None
    failing_check: str | None = None  # the check that gave the lowest score
    error_type: str | None = None  # the failing span's exception type, when it has one


class TraceScore(BaseModel):
    """One check's score of a trace: 0.0 bad, 1.0 fine; a bad score blames a span."""

    evaluator: str
    value: float
    span_id: str | None = None
    failed: bool = False  # value <= FAILED_MAX_SCORE: the one place the threshold is applied


def is_failed(score: float | None) -> bool:
    """Whether a trace's lowest score, or one check's score, counts as a failure."""
    return score is not None and score <= FAILED_MAX_SCORE


class TraceDetail(BaseModel):
    """One trace for the trace viewer: its span tree and every score it got."""

    trace_id: str
    tree: SpanNode
    scores: list[TraceScore]
    min_score: float | None  # None: not scored yet
    failed: bool
