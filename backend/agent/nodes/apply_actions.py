"""apply_actions: the graph's only writing node. It acts on approved proposals and nothing else."""

from langgraph.runtime import Runtime

from agent.actions import append_regression_cases, write_dry_run
from agent.context import TraceContext
from agent.schemas import Proposal
from agent.state import TriageState


async def apply_actions(state: TriageState, runtime: Runtime[TraceContext]) -> dict:
    """Write the issue and the regression case of every approved proposal.

    A dry run writes local files (agent.actions). A real run opens one GitHub issue per approved
    proposal (agent.github), then appends the regression cases. Any GitHub error is raised, so the
    review fails; a resubmitted review opens only the issues still missing.
    """
    context = runtime.context
    decisions = state.get("decisions", {})
    approved = [
        Proposal.model_validate(p)
        for p in state.get("proposals", [])
        if decisions.get(p["cluster_id"]) == "approve"
    ]
    if context.dry_run:
        return {"actions_log": write_dry_run(approved, context.out_dir)}
    if context.github is None:  # main.py refuses this at startup
        raise RuntimeError("DRY_RUN is off but there is no GitHub writer")
    # The run's id (runs.Runs uses it as the thread id). The issue markers need it, or a retry
    # could open an issue twice; it is there whenever the graph has a checkpointer.
    info = runtime.execution_info
    if info is None or not info.thread_id:
        raise RuntimeError("a real run needs a thread id")
    log = await context.github.open_issues(info.thread_id, approved)
    return {"actions_log": log + append_regression_cases(approved, context.out_dir)}
