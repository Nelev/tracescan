"""POST /v1/runs: trigger one triage run and return a summary.

The response carries counts and the actions log only, never the raw state: failed traces can hold
clinical span data. A run opens its own TraceClient because the trace session lives for exactly
one graph invocation (see agent.mcp_client).
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from langchain_core.runnables import RunnableConfig

from agent.const import MAX_PARALLEL_BRANCHES
from agent.context import TraceContext
from agent.mcp_client import TraceClient
from agent.state import TriageState
from api.schemas import RunRequest, RunResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


@router.post("/runs")
async def create_run(body: RunRequest, request: Request) -> RunResponse:
    state = TriageState(target_app=body.target_app)
    if body.since is not None:
        state["since"] = body.since.isoformat()
    if body.until is not None:
        state["until"] = body.until.isoformat()

    # A fresh thread per run: reusing a thread id would continue the earlier run's state.
    run_id = str(uuid4())
    config: RunnableConfig = {
        "configurable": {"thread_id": run_id},
        "max_concurrency": MAX_PARALLEL_BRANCHES,
    }

    try:
        async with TraceClient() as traces:
            context = TraceContext(traces, request.app.state.embedder, request.app.state.model)
            result = await request.app.state.graph.ainvoke(state, config, context=context)
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
        diagnosis_failures=len(result.get("diagnosis_failures", [])),
        proposals=len(result.get("proposals", [])),
        actions_log=result.get("actions_log", []),
    )
