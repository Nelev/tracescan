"""POST /v1/runs: trigger one triage run and return a summary.

The response carries counts and the actions log only, never the raw state: failed traces can hold
clinical span data. A run opens its own TraceClient because the trace session lives for exactly
one graph invocation (see agent.mcp_client).
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from langchain_core.runnables import RunnableConfig
from pydantic import AwareDatetime, BaseModel

from agent.context import TraceContext
from agent.mcp_client import TraceClient
from agent.state import TriageState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


class RunRequest(BaseModel):
    target_app: str
    since: AwareDatetime | None = None  # inclusive
    until: AwareDatetime | None = None  # exclusive


class RunResponse(BaseModel):
    run_id: str  # the graph's thread_id
    failed_traces: int
    clusters: int
    unclustered: int  # failures that fit no cluster; kept, not diagnosed
    diagnoses: int
    proposals: int
    actions_log: list[str]


@router.post("/runs")
async def create_run(body: RunRequest, request: Request) -> RunResponse:
    state = TriageState(target_app=body.target_app)
    if body.since is not None:
        state["since"] = body.since.isoformat()
    if body.until is not None:
        state["until"] = body.until.isoformat()

    # A fresh thread per run: reusing a thread id would continue the earlier run's state.
    run_id = str(uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": run_id}}

    try:
        async with TraceClient() as traces:
            result = await request.app.state.graph.ainvoke(
                state, config, context=TraceContext(traces, embedder=request.app.state.embedder)
            )
    except Exception as exc:
        # Type name only: the message or traceback could carry span contents.
        logger.error("triage run failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="triage run failed") from None

    return RunResponse(
        run_id=run_id,
        failed_traces=len(result.get("failed_traces", [])),
        clusters=len(result.get("clusters", [])),
        unclustered=len(result.get("unclustered", [])),
        diagnoses=len(result.get("diagnoses", [])),
        proposals=len(result.get("proposals", [])),
        actions_log=result.get("actions_log", []),
    )
