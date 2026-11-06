"""Contracts for the trace-reading MCP tools (search_failed_traces, get_trace_tree, get_span)."""

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

from trace_store.const import MAX_LIMIT

SpanStatus = Literal["unset", "ok", "error"]


class FailedTraceQuery(BaseModel):
    """Input of search_failed_traces. A trace is failed if its status is error or its lowest score is <= max_score."""

    app: str
    since: AwareDatetime | None = None  # inclusive
    until: AwareDatetime | None = None  # exclusive
    max_score: float = 0.5
    limit: int = Field(default=50, ge=1, le=MAX_LIMIT)


class TraceSummary(BaseModel):
    """One row from search_failed_traces. Small enough to cluster without fetching trees."""

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
