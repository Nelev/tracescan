"""The runs module's data: what `Runs` answers and streams, and what the run store records.

Plain data only, no behaviour: the service is runs.service, the store runs.store. Nothing here
holds span content; the proposals' and diagnoses' prose is the model's own, so it goes to whoever
reviews the run and is never logged.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from agent.model_guard import Spent
from agent.schemas import (
    ClusterMap,
    ClusterMethod,
    Decision,
    ProgressEvent,
    Proposal,
    StoredDiagnosis,
)
from db.models import RunStatus as StoredStatus

# Where a run stands. The checkpoint can tell that it waits for review or reached its end;
# `failed` and `aborted` come from the run store. The store's statuses are the same five.
RunState = StoredStatus


class RunSummary(BaseModel):
    """Counts and the actions log. The only view of a run's state besides its proposals."""

    run_id: str  # the graph's thread_id
    traces: int  # in the window, up to MAX_JUDGED_TRACES; each is judged
    judged: int  # traces the judge gave a verdict on
    judge_failures: int  # traces whose judging failed; they are not clustered
    failed_traces: int
    clusters: int
    unclustered: int  # failures that fit no cluster; each is diagnosed on its own
    diagnoses: int
    diagnosis_failures: int  # clusters whose diagnosis failed; reported, not dropped
    proposals: int
    actions_log: list[str]


class RunStatus(BaseModel):
    """Where a run stands, read from its checkpoint.

    The proposals' issue text is the diagnoser's own prose, so it can hold clinical content: it
    goes to whoever reviews the run, and is never logged.
    """

    status: RunState
    summary: RunSummary
    proposals: list[Proposal]


class ClusterDetail(BaseModel):
    """One cluster of failed traces, and what the run made of it."""

    cluster_id: str
    signature: str  # names only: the failing span and its error type or check
    method: ClusterMethod
    trace_ids: list[str]
    exemplar_trace_ids: list[str]  # the ones the diagnoser was shown
    diagnosis: StoredDiagnosis | None  # None until diagnosed, or when it failed
    diagnosis_failed: bool
    usage: Spent  # over all its attempts, failed ones included
    verification: str  # unverified until the reproducer exists
    decision: Decision | None  # the reviewer's, once the run is reviewed


class RunDetail(BaseModel):
    """What a run found, cluster by cluster: ids, signatures, diagnoses, spend and decisions.

    No span content: a trace is an id here, and the UI reads it from the trace store. The
    diagnoses' prose is the model's own, so it goes where the proposals go and is never logged.
    """

    status: RunState
    # It failed or was aborted with steps left in its checkpoint: `Runs.resume` can go on with it.
    resumable: bool = False
    summary: RunSummary
    clusters: list[ClusterDetail]  # a failure that fit no cluster is an `isolated` one
    # The failures in 3D, for the run page's map. None before clustering, for a run too small
    # to embed, and for runs clustered before the map existed.
    cluster_map: ClusterMap | None = None


@dataclass(frozen=True)
class Progress:
    data: ProgressEvent  # allowlisted by agent.progress: ids and counts only


@dataclass(frozen=True)
class Ended:
    """The last event of a run that did not fail: it waits for review, or had nothing to review."""

    status: RunStatus


@dataclass(frozen=True)
class Failed:
    """The last event of a run that failed. No detail: the cause could carry span contents."""


RunEvent = Progress | Ended | Failed


@dataclass(frozen=True)
class StartedRun:
    run_id: str
    events: AsyncIterator[RunEvent]  # Progress*, then exactly one Ended or Failed


# --- The run store's records


@dataclass(frozen=True)
class RunCounts:
    failed_traces: int
    clusters: int
    proposals: int


class RunRecord(BaseModel):
    """One row of `runs`."""

    run_id: str
    target_app: str
    since: datetime | None
    until: datetime | None
    status: StoredStatus
    started_by: str | None  # a name as the client sent it; None only on old rows
    created_at: datetime
    ended_at: datetime | None
    failed_traces: int
    clusters: int
    proposals: int


class ReviewRecord(BaseModel):
    cluster_id: str
    decision: Decision
    reviewer: str
    decided_at: datetime
