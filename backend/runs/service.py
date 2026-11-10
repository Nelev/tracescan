"""The life of a triage run: start it, read its status, resume it with the review decisions.

The one module that knows a run is a graph thread. The thread id, the graph config, the
`TraceContext` and the trace session stay behind `Runs`; callers get typed events and summaries,
never raw graph state, which can hold clinical span data.

There is no runs table. The checkpoint is the only record of a run, so its status is read from
there, and the server cannot list runs: a client keeps its `run_id`.
"""

import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.stream import AsyncGraphRunStream
from langgraph.types import Command, StateSnapshot
from pydantic import BaseModel

from agent.context import ClosedTraces, TraceAccess, TraceContext
from agent.embeddings import Embedder
from agent.progress import ProgressEvent, progress_events
from agent.schemas import Decision, Proposal
from agent.state import TriageState

logger = logging.getLogger(__name__)

# `in_progress` is any run that neither waits for review nor reached its end. With no runs table
# that includes a run that was aborted or that failed: the checkpoint cannot tell them apart.
RunState = Literal["in_progress", "review_required", "completed"]

OpenTraces = Callable[[], AbstractAsyncContextManager[TraceAccess]]


class RunSummary(BaseModel):
    """Counts and the actions log. The only view of a run's state besides its proposals."""

    run_id: str  # the graph's thread_id
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


def _state_of(snapshot: StateSnapshot) -> RunState:
    if not snapshot.next:
        return "completed"
    return "review_required" if snapshot.interrupts else "in_progress"


class Runs:
    """Built once at startup with everything a run needs; `open_traces` opens one trace session."""

    def __init__(
        self,
        graph: CompiledStateGraph,
        embedder: Embedder,
        model: BaseChatModel,
        open_traces: OpenTraces,
    ) -> None:
        self._graph = graph  # must have a checkpointer: status and review read it
        self._embedder = embedder
        self._model = model
        self._open_traces = open_traces
        self._resuming: set[str] = set()  # runs whose review is being applied, in this process

    @asynccontextmanager
    async def start(
        self, target_app: str, since: datetime | None = None, until: datetime | None = None
    ) -> AsyncIterator[StartedRun]:
        """Start a run on a fresh thread and yield its id and events.

        The trace session and the graph stream live as long as this context. Leaving it early
        aborts the run: a run is durable only once it waits for review. Raises `RunFailed` when
        the trace session or the stream cannot open.
        """
        state = TriageState(target_app=target_app)
        if since is not None:
            state["since"] = since.isoformat()
        if until is not None:
            state["until"] = until.isoformat()
        # A fresh thread per run: reusing a thread id would continue the earlier run's state.
        run_id = str(uuid4())
        async with AsyncExitStack() as stack:
            try:
                traces = await stack.enter_async_context(self._open_traces())
                context = TraceContext(traces, self._embedder, self._model)
                run = self._graph.astream_events(
                    state, _config(run_id), version="v3", context=context
                )
                stream = await stack.enter_async_context(await run)
            except Exception as exc:
                _log_failure(exc)
                raise RunFailed from None
            yield StartedRun(run_id, self._events(run_id, stream))

    async def _events(self, run_id: str, stream: AsyncGraphRunStream) -> AsyncIterator[RunEvent]:
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
            yield Failed()
            return
        yield Ended(status)

    async def _snapshot(self, run_id: str) -> StateSnapshot:
        snapshot = await self._graph.aget_state(_config(run_id))
        if snapshot.created_at is None:
            raise RunNotFound
        return snapshot

    async def status(self, run_id: str) -> RunStatus:
        """The run's status, counts and proposals. Raises `RunNotFound`."""
        snapshot = await self._snapshot(run_id)
        return _status(run_id, snapshot.values, _state_of(snapshot))

    async def review(self, run_id: str, decisions: Mapping[str, Decision]) -> RunStatus:
        """Resume a run that waits for review and return where it ended.

        Needs one decision per proposal, no more and no fewer. The resume opens no trace session:
        apply_actions works from the approved proposals already in state. Raises `RunNotFound`,
        `NotWaitingForReview`, `IncompleteDecisions`, or `RunFailed` when the resume fails.
        """
        snapshot = await self._snapshot(run_id)
        if _state_of(snapshot) != "review_required" or run_id in self._resuming:
            raise NotWaitingForReview
        # What human_review asked: the ids in its interrupt value are the ones to decide.
        expected = set(snapshot.interrupts[0].value["cluster_ids"])
        if expected != set(decisions):
            raise IncompleteDecisions(
                missing=sorted(expected - set(decisions)), unknown=sorted(set(decisions) - expected)
            )
        # No await between the check above and this line, so two reviews cannot both pass it.
        self._resuming.add(run_id)
        try:
            context = TraceContext(ClosedTraces(), self._embedder, self._model)
            values = await self._graph.ainvoke(
                Command(resume=dict(decisions)), _config(run_id), context=context
            )
        except Exception as exc:
            _log_failure(exc)
            raise RunFailed from None
        finally:
            self._resuming.discard(run_id)
        # The resume returns the final state, so the checkpoint is not read again.
        paused = "__interrupt__" in values
        return _status(run_id, values, "review_required" if paused else "completed")
