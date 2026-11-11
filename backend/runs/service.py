"""The life of a triage run: start it, read its status, resume it with the review decisions.

The one module that knows a run is a graph thread. The thread id, the graph config, the
`TraceContext` and the trace session stay behind `Runs`; callers get typed events and summaries,
never raw graph state, which can hold clinical span data.

A run has two records. The checkpoint holds its state and proposals and decides what the run
can do next. The run store (runs.store) is the index around it: which runs exist, who started
them, how each ended, and who decided what. Where the two disagree the checkpoint wins, except
that only the store knows a run failed or was aborted.
"""

import logging
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import uuid4

import anyio
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.stream import AsyncGraphRunStream
from langgraph.types import Command, StateSnapshot
from pydantic import BaseModel

from agent.context import ClosedTraces, TraceAccess, TraceContext
from agent.model_guard import Spent, spent_by
from agent.progress import ProgressEvent, progress_events
from agent.schemas import ClusterMethod, Decision, Proposal, StoredDiagnosis
from agent.state import TriageState
from runs.store import NotClaimable, RunCounts, RunRecord, RunStore, StoredStatus

logger = logging.getLogger(__name__)

# Where a run stands. The checkpoint can tell that it waits for review or reached its end;
# `failed` and `aborted` come from the run store. The store's statuses are the same five.
RunState = StoredStatus

OpenTraces = Callable[[], AbstractAsyncContextManager[TraceAccess]]


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
    summary: RunSummary
    clusters: list[ClusterDetail]  # a failure that fit no cluster is an `isolated` one


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


# What `Runs` raises. None of them carries state or an underlying message.


class RunFailed(Exception):
    """The run could not start, or its resume failed."""


class RunNotFound(Exception):
    """No checkpoint for this run id."""


class NotWaitingForReview(Exception):
    """The run is not paused at the review, or its review is already being applied."""


class IncompleteDecisions(Exception):
    """The decisions do not cover exactly the run's proposals."""

    def __init__(self, missing: list[str], unknown: list[str]) -> None:
        super().__init__("the decisions do not match the proposals")
        self.missing = missing  # cluster ids with no decision
        self.unknown = unknown  # decided cluster ids the run has no proposal for


@dataclass(frozen=True)
class StartedRun:
    run_id: str
    events: AsyncIterator[RunEvent]  # Progress*, then exactly one Ended or Failed


def _config(run_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": run_id}}


def _log_failure(exc: Exception) -> None:
    # Type name only: the message or traceback could carry span contents.
    logger.error("triage run failed: %s", type(exc).__name__)


def _summary(run_id: str, values: Mapping) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        traces=len(values.get("traces", [])),
        judged=len(values.get("verdicts", [])),
        judge_failures=len(values.get("judge_failures", [])),
        failed_traces=len(values.get("failed_traces", [])),
        clusters=len(values.get("clusters", [])),
        unclustered=len(values.get("unclustered", [])),
        diagnoses=len(values.get("diagnoses", [])),
        diagnosis_failures=len(values.get("diagnosis_failures", [])),
        proposals=len(values.get("proposals", [])),
        actions_log=values.get("actions_log", []),
    )


def _status(run_id: str, values: Mapping, state: RunState) -> RunStatus:
    proposals = [Proposal.model_validate(p) for p in values.get("proposals", [])]
    return RunStatus(status=state, summary=_summary(run_id, values), proposals=proposals)


def _detail(run_id: str, values: Mapping, state: RunState) -> RunDetail:
    diagnoses = {d["cluster_id"]: d for d in values.get("diagnoses", [])}
    failures = set(values.get("diagnosis_failures", []))
    spent = spent_by(values.get("model_usage", []))
    verification = {
        p["cluster_id"]: p.get("verification", "unverified") for p in values.get("proposals", [])
    }
    decisions = values.get("decisions", {})
    clusters = []
    for cluster in values.get("clusters", []):
        cluster_id = cluster["cluster_id"]
        diagnosis = diagnoses.get(cluster_id)
        clusters.append(
            ClusterDetail(
                cluster_id=cluster_id,
                signature=cluster["signature"],
                method=cluster["method"],
                trace_ids=cluster["trace_ids"],
                exemplar_trace_ids=cluster["exemplar_trace_ids"],
                diagnosis=diagnosis and StoredDiagnosis.model_validate(diagnosis),
                diagnosis_failed=cluster_id in failures,
                usage=spent.get(cluster_id, Spent()),
                verification=verification.get(cluster_id, "unverified"),
                decision=decisions.get(cluster_id),
            )
        )
    return RunDetail(
        status=state,
        summary=_summary(run_id, values),
        clusters=clusters,
    )


def _state_of(snapshot: StateSnapshot) -> RunState:
    if not snapshot.next:
        return "completed"
    return "review_required" if snapshot.interrupts else "in_progress"


def _resolve(snapshot: StateSnapshot | None, record: RunRecord | None) -> RunState:
    """Where a run stands, from its two records. Raises `RunNotFound` when it has neither."""
    if record is not None and record.status in {"failed", "aborted"}:
        # Only the store knows the run stopped for good. The checkpoint of a run cut short
        # cannot tell: between the clustering and the diagnose branches it even reads as ended.
        return record.status
    if snapshot is not None:
        return _state_of(snapshot)
    if record is None:
        raise RunNotFound
    # Recorded, but it never got as far as a checkpoint: it just started.
    return record.status


def _counts(summary: RunSummary) -> RunCounts:
    return RunCounts(summary.failed_traces, summary.clusters, summary.proposals)


class Runs:
    """Built once at startup with everything a run needs; `open_traces` opens one trace session."""

    def __init__(
        self,
        graph: CompiledStateGraph[Any, TraceContext, Any, Any],
        context: TraceContext,
        open_traces: OpenTraces,
        store: RunStore,
    ) -> None:
        self._graph = graph  # must have a checkpointer: status and review read it
        # What every run segment gets, set once by the server so no request reaches it. Its
        # `traces` is replaced per segment: an open session to start, ClosedTraces to review.
        self._context = context
        self._open_traces = open_traces
        self._store = store

    async def _mark(
        self, run_id: str, status: StoredStatus, counts: RunCounts | None = None
    ) -> None:
        """Record where a run stands. Best effort: the checkpoint, not this row, drives the run."""
        try:
            await self._store.set_status(run_id, status, counts)
        except Exception as exc:
            logger.error("run %s: status %s not recorded: %s", run_id, status, type(exc).__name__)

    @asynccontextmanager
    async def start(
        self,
        target_app: str,
        user: str,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AsyncGenerator[StartedRun]:
        """Start a run on a fresh thread, in `user`'s name, and yield its id and events.

        The trace session and the graph stream live as long as this context. Leaving it early
        aborts the run, which is recorded as `aborted`: a run is durable only once it waits for
        review. Raises `RunFailed` when the run cannot be recorded or the trace session or the
        stream cannot open.
        """
        state = TriageState(target_app=target_app)
        if since is not None:
            state["since"] = since.isoformat()
        if until is not None:
            state["until"] = until.isoformat()
        # A fresh thread per run: reusing a thread id would continue the earlier run's state.
        run_id = str(uuid4())
        ended: list[RunState] = []  # filled by the events once the run has ended or failed
        async with AsyncExitStack() as stack:
            try:
                await self._store.create_run(run_id, target_app, since, until, "in_progress", user)
                traces = await stack.enter_async_context(self._open_traces())
                run = self._graph.astream_events(
                    state,
                    _config(run_id),
                    version="v3",
                    context=replace(self._context, traces=traces),
                )
                stream = await stack.enter_async_context(await run)
            except Exception as exc:
                _log_failure(exc)
                await self._mark(run_id, "failed")
                raise RunFailed from None
            try:
                yield StartedRun(run_id, self._events(run_id, stream, ended))
            finally:
                if not ended:
                    # Left early, usually by a client that disconnected: the request is being
                    # cancelled, so shield the one write that says what happened.
                    with anyio.CancelScope(shield=True):
                        await self._mark(run_id, "aborted")

    async def _events(
        self, run_id: str, stream: AsyncGraphRunStream, ended: list[RunState]
    ) -> AsyncIterator[RunEvent]:
        try:
            # Only the progress channel: the raw stream carries full state.
            async for progress in progress_events(stream):
                yield Progress(progress)
            values = await stream.output()  # raises what a failing node raised
            if values is None:  # no final state: a failure, not an empty run
                raise RuntimeError("run produced no output")
            # A stream that ended without an error either paused at the review or reached its end.
            paused = await stream.interrupted()
            status = _status(run_id, values, "review_required" if paused else "completed")
        except Exception as exc:
            _log_failure(exc)
            ended.append("failed")
            await self._mark(run_id, "failed")
            yield Failed()
            return
        ended.append(status.status)
        await self._mark(run_id, status.status, _counts(status.summary))
        yield Ended(status)

    async def _find_snapshot(self, run_id: str) -> StateSnapshot | None:
        snapshot = await self._graph.aget_state(_config(run_id))
        return None if snapshot.created_at is None else snapshot

    async def _snapshot(self, run_id: str) -> StateSnapshot:
        snapshot = await self._find_snapshot(run_id)
        if snapshot is None:
            raise RunNotFound
        return snapshot

    async def list(self, limit: int = 50) -> list[RunRecord]:
        """The newest runs first, as the run store recorded them: no state, no proposals."""
        return await self._store.list_runs(limit)

    async def _load(self, run_id: str) -> tuple[Mapping, RunState]:
        """The run's state values and where it stands, from its two records."""
        record = await self._store.get_run(run_id)
        snapshot = await self._find_snapshot(run_id)
        state = _resolve(snapshot, record)
        return (snapshot.values if snapshot else {}), state

    async def status(self, run_id: str) -> RunStatus:
        """The run's status, counts and proposals. Raises `RunNotFound`."""
        return _status(run_id, *await self._load(run_id))

    async def detail(self, run_id: str) -> RunDetail:
        """What the run found, cluster by cluster. Raises `RunNotFound`."""
        return _detail(run_id, *await self._load(run_id))

    async def review(
        self, run_id: str, decisions: Mapping[str, Decision], reviewer: str
    ) -> RunStatus:
        """Resume a run that waits for review, in `reviewer`'s name, and return where it ended.

        Needs one decision per proposal, no more and no fewer. The review is one transaction in
        the run store: it holds the run against a second review, in this process or another, and
        keeps the decisions and the run's new status only if the resume succeeds. The resume opens
        no trace session: apply_actions works from the approved proposals already in state.
        Raises `RunNotFound`, `NotWaitingForReview`, `IncompleteDecisions`, or `RunFailed` when
        the resume or the store fails.
        """
        snapshot = await self._snapshot(run_id)
        if _state_of(snapshot) != "review_required":
            raise NotWaitingForReview
        # What human_review asked: the ids in its interrupt value are the ones to decide.
        expected = set(snapshot.interrupts[0].value["cluster_ids"])
        if expected != set(decisions):
            raise IncompleteDecisions(
                missing=sorted(expected - set(decisions)), unknown=sorted(set(decisions) - expected)
            )
        try:
            async with self._store.reviewing(run_id, decisions, reviewer) as finish:
                values = await self._graph.ainvoke(
                    Command(resume=dict(decisions)),
                    _config(run_id),
                    context=replace(self._context, traces=ClosedTraces()),
                )
                # The resume returns the final state, so the checkpoint is not read again.
                paused = "__interrupt__" in values
                status = _status(run_id, values, "review_required" if paused else "completed")
                await finish(status.status, _counts(status.summary))
                return status
        except NotClaimable:
            # Another review holds it, or it ended since the checkpoint was read.
            raise NotWaitingForReview from None
        except Exception as exc:
            _log_failure(exc)
            raise RunFailed from None
