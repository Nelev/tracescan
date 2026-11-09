"""POST /v1/runs: trigger one triage run and return a summary; POST /v1/runs/stream: the same run
as a server-sent event stream.

The sync response carries counts and the actions log only, never the raw state: failed traces can
hold clinical span data. Only the stream also sends the drafted proposals, as `proposal` events. A run opens its own TraceClient because the trace session lives for exactly
one graph invocation (see agent.mcp_client).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.runnables import RunnableConfig
from langgraph.stream import AsyncGraphRunStream

from agent.context import TraceContext
from agent.mcp_client import TraceClient
from agent.progress import progress_events
from agent.schemas import Proposal
from agent.state import TriageState
from api.schemas import RunRequest, RunResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


def _initial_state(body: RunRequest) -> TriageState:
    state = TriageState(target_app=body.target_app)
    if body.since is not None:
        state["since"] = body.since.isoformat()
    if body.until is not None:
        state["until"] = body.until.isoformat()
    return state


def _new_run() -> tuple[str, RunnableConfig]:
    # A fresh thread per run: reusing a thread id would continue the earlier run's state.
    run_id = str(uuid4())
    return run_id, {"configurable": {"thread_id": run_id}}


def _context(request: Request, traces: TraceClient) -> TraceContext:
    return TraceContext(traces, request.app.state.embedder, request.app.state.model)


def _log_failure(exc: Exception) -> None:
    # Type name only: the message or traceback could carry span contents.
    logger.error("triage run failed: %s", type(exc).__name__)


def _summary(run_id: str, result: dict) -> RunResponse:
    return RunResponse(
        run_id=run_id,
        failed_traces=len(result.get("failed_traces", [])),
        clusters=len(result.get("clusters", [])),
        unclustered=len(result.get("unclustered", [])),
        diagnoses=len(result.get("diagnoses", [])),
        diagnosis_failures=len(result.get("diagnosis_failures", [])),
        proposals=len(result.get("proposals", [])),
        actions_log=result.get("actions_log", []),
    )


def _proposals(result: dict) -> list[dict]:
    """The drafted proposals, cut to the `Proposal` schema's fields.

    The one part of state besides counts that leaves the server, and only on the stream. The issue
    text is the diagnoser's own prose, so it can hold clinical content: it goes to whoever runs the
    triage, to review it, and is never logged.
    """
    return [Proposal.model_validate(p).model_dump(mode="json") for p in result.get("proposals", [])]


@router.post("/runs")
async def create_run(body: RunRequest, request: Request) -> RunResponse:
    run_id, config = _new_run()
    try:
        async with TraceClient() as traces:
            result = await request.app.state.graph.ainvoke(
                _initial_state(body), config, context=_context(request, traces)
            )
    except Exception as exc:
        _log_failure(exc)
        raise HTTPException(status_code=502, detail="triage run failed") from None
    return _summary(run_id, result)


async def _open_run(
    body: RunRequest, request: Request
) -> AsyncIterator[tuple[str, AsyncGraphRunStream]]:
    """Own the trace session and the run stream for the whole response.

    FastAPI unwinds a dependency when the response ends, including when the client disconnects.
    A generator suspended at a `yield` is not closed on disconnect, so the endpoint must not own
    these itself: the run would keep going, and keep the trace session open, until garbage
    collection.
    """
    run_id, config = _new_run()
    async with AsyncExitStack() as stack:
        try:
            traces = await stack.enter_async_context(TraceClient())
            run = request.app.state.graph.astream_events(
                _initial_state(body), config, version="v3", context=_context(request, traces)
            )
            stream = await stack.enter_async_context(await run)
        except Exception as exc:
            _log_failure(exc)
            raise HTTPException(status_code=502, detail="triage run failed") from None
        yield run_id, stream


@router.post("/runs/stream", response_class=EventSourceResponse)
async def stream_run(
    opened: Annotated[tuple[str, AsyncGraphRunStream], Depends(_open_run)],
) -> AsyncIterator[ServerSentEvent]:
    """Stream a run: `run_started`, `progress`*, `proposal`*, then `run_completed` or `run_failed`.

    A failed run sends no proposals.
    """
    run_id, stream = opened
    yield ServerSentEvent(event="run_started", data={"run_id": run_id})
    try:
        async for progress in progress_events(stream):
            yield ServerSentEvent(event="progress", data=progress)
        result = await stream.output()
        if result is None:  # no final state: report the failure, not an empty run
            raise RuntimeError("run produced no output")
        summary = _summary(run_id, result)
        # Built before the first yield: a bad entry fails the run, not half the stream.
        proposals = _proposals(result)
    except Exception as exc:
        _log_failure(exc)
        # The status is already 200 once the stream opens, so the failure travels as an event.
        yield ServerSentEvent(event="run_failed", data={})
        return
    for proposal in proposals:
        yield ServerSentEvent(event="proposal", data=proposal)
    yield ServerSentEvent(event="run_completed", data=summary)
