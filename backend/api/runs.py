"""The runs API: HTTP and server-sent events over the runs module (runs.Runs), nothing more.

- `POST /v1/runs/stream` starts a run and streams it until it waits for review or ends.
- `GET /v1/runs` lists the newest runs: who started each, its status and counts.
- `GET /v1/runs/{run_id}` returns its status, counts and proposals, read from the checkpoint.
- `GET /v1/runs/{run_id}/detail` returns its clusters: signatures, trace ids, diagnoses with the
  span ids they cite, spend and decisions.
- `POST /v1/runs/{run_id}/review` resumes it with one decision per proposal.

Every route needs a Clerk session token (auth.session, required for this router in main.py):
`401` without a valid one, `503` when it cannot be verified, both before a run or a trace session
is opened. Starting a run is also limited per person (api.rate_limit, a `429`). Who starts or
reviews a run is recorded under the name the token carries, never one the request sends.

No response carries raw state: failed traces can hold clinical span data. What leaves the server
is counts, the actions log and the drafted proposals, plus on the stream the UI spec the small
model writes for each message (api.ui_spec).
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent

from api.rate_limit import limit_runs
from api.schemas import TOTAL_COUNT, ReviewRequest, ReviewResponse, RunRequest
from api.ui_spec import UiSpecs
from auth import CurrentUser
from runs import (
    Ended,
    IncompleteDecisions,
    NotWaitingForReview,
    Progress,
    RunDetail,
    RunFailed,
    RunNotFound,
    RunRecord,
    Runs,
    RunStatus,
    StartedRun,
)

router = APIRouter(prefix="/v1")

# The stream's last message for each way a run can end without failing.
_LAST_MESSAGE = {"review_required": "review_required", "completed": "run_completed"}


def _run_failed() -> HTTPException:
    return HTTPException(status_code=502, detail="triage run failed")


def _run_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="run not found")


def _runs(request: Request) -> Runs:
    return request.app.state.runs


async def _open_run(
    body: RunRequest,
    runs: Annotated[Runs, Depends(_runs)],
    user: CurrentUser,
) -> AsyncIterator[StartedRun]:
    """Own the started run for the whole response.

    FastAPI unwinds a dependency when the response ends, including when the client disconnects.
    A generator suspended at a `yield` is not closed on disconnect, so the endpoint must not own
    the run itself: it would keep going, and keep the trace session open, until garbage
    collection.
    """
    try:
        async with runs.start(body.target_app, user.name, body.since, body.until) as run:
            yield run
    except RunFailed:
        # Raised only while opening, so before the stream starts: a plain 502.
        raise _run_failed() from None


@router.post("/runs/stream", response_class=EventSourceResponse, dependencies=[Depends(limit_runs)])
async def stream_run(
    run: Annotated[StartedRun, Depends(_open_run)], request: Request
) -> AsyncIterator[ServerSentEvent]:
    """Stream a run: `run_started`, `progress`*, `proposal`*, then its last message.

    The last message is `review_required` (the run waits at the review; decide it with
    `POST /v1/runs/{run_id}/review`), `run_completed` (it ended with nothing to review) or
    `run_failed {}`. The first two carry the run's summary; the proposals to decide are the
    `proposal` messages just before.

    Each message except `run_failed` is followed by a `ui_spec {event, spec}`: the UI spec the small
    model wrote for it (api.ui_spec), sent once its call is done, so a message is never held back
    by its own call, only the next one is. A message whose call failed, was too slow or was past
    the run's call limit has none. A failed run sends no proposals.
    """
    ui = UiSpecs(request.app.state.ui_spec_model)

    async def message(event: str, data: dict) -> AsyncIterator[ServerSentEvent]:
        """A message, then the UI spec the model writes for it, if any."""
        yield ServerSentEvent(event=event, data=data)
        # Awaited here, not in a task: a client that leaves cancels the request, and with it the call.
        spec = await ui.compose(event, data)
        if spec is not None:
            yield ServerSentEvent(event="ui_spec", data={"event": event, "spec": spec})

    async for sse in message("run_started", {"run_id": run.run_id}):
        yield sse
    async for event in run.events:
        if isinstance(event, Progress):
            async for sse in message("progress", dict(event.data)):
                yield sse
        elif isinstance(event, Ended):
            status = event.status
            for proposal in status.proposals:
                async for sse in message("proposal", proposal.model_dump(mode="json")):
                    yield sse
            name = _LAST_MESSAGE[status.status]
            async for sse in message(name, status.summary.model_dump(mode="json")):
                yield sse
        else:
            # Failed. The status is already 200 once the stream opens, so the failure travels
            # as an event.
            yield ServerSentEvent(event="run_failed", data={})


@router.get("/runs")
async def list_runs(
    runs: Annotated[Runs, Depends(_runs)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunRecord]:
    """The newest runs first: ids, names, statuses and counts, never state or proposals.

    One page of them: `limit` runs after the newest `offset`. The total over all pages is the
    `X-Total-Count` header, so the body stays a plain list.
    """
    # Two independent reads, each on its own pooled connection: run together, not one after the other.
    total, page = await asyncio.gather(runs.count(), runs.list(limit, offset))
    response.headers[TOTAL_COUNT] = str(total)
    return page


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, runs: Annotated[Runs, Depends(_runs)]) -> RunStatus:
    try:
        return await runs.status(str(run_id))
    except RunNotFound:
        raise _run_not_found() from None


@router.get("/runs/{run_id}/detail")
async def get_run_detail(run_id: UUID, runs: Annotated[Runs, Depends(_runs)]) -> RunDetail:
    """What the run found, cluster by cluster: no span content, trace and span ids only."""
    try:
        return await runs.detail(str(run_id))
    except RunNotFound:
        raise _run_not_found() from None


@router.post("/runs/{run_id}/review")
async def review_run(
    run_id: UUID,
    body: ReviewRequest,
    runs: Annotated[Runs, Depends(_runs)],
    user: CurrentUser,
) -> ReviewResponse:
    """Resume a run that waits for review. `409` when it does not, `422` for a partial review."""
    try:
        status = await runs.review(str(run_id), body.decisions, user.name)
    except RunNotFound:
        raise _run_not_found() from None
    except NotWaitingForReview:
        raise HTTPException(status_code=409, detail="run is not waiting for review") from None
    except IncompleteDecisions as exc:
        # Cluster ids only: they are already in the proposals the reviewer holds.
        detail = {"missing": exc.missing, "unknown": exc.unknown}
        raise HTTPException(status_code=422, detail=detail) from None
    except RunFailed:
        raise _run_failed() from None
    return ReviewResponse(status=status.status, summary=status.summary)
