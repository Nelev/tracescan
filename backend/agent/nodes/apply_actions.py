"""apply_actions: the graph's only writing node. It acts on reviewed proposals and nothing else."""

import logging

from langgraph.runtime import Runtime

from agent.actions import append_regression_cases, write_dry_run
from agent.context import TraceContext
from agent.memory import issue_memories
from agent.schemas import Proposal
from agent.state import TriageState

logger = logging.getLogger(__name__)


async def apply_actions(state: TriageState, runtime: Runtime[TraceContext]) -> dict:
    """Write the issue and the regression case of every approved proposal, then remember every
    decided one.

    A dry run writes local files (agent.actions). A real run opens one GitHub issue per approved
    proposal (agent.github), then appends the regression cases. Any GitHub error is raised, so the
    review fails; a resubmitted review opens only the issues still missing.

    Last, with a known-issues memory in the context, every decided and diagnosed proposal is saved
    there (agent.memory), approved ones as confirmed causes and rejected ones as warnings. Its ids
    are the run's and the cluster's, so an apply that runs again replaces them; an error raises.
    """
    context = runtime.context
    decisions = state.get("decisions", {})
    approved = [
        Proposal.model_validate(p)
        for p in state.get("proposals", [])
        if decisions.get(p["cluster_id"]) == "approve"
    ]
    # The run's id (runs.Runs uses it as the thread id), there whenever the graph has a
    # checkpointer. The issue markers and the regression cases are keyed on it, so an apply that
    # runs again (a resumed run) opens and appends only what is still missing.
    info = runtime.execution_info
    run_id = info.thread_id if info is not None and info.thread_id else None
    if context.dry_run:
        log = write_dry_run(approved, context.out_dir, run_id)
    else:
        if context.github is None:  # main.py refuses this at startup
            raise RuntimeError("DRY_RUN is off but there is no GitHub writer")
        if run_id is None:
            raise RuntimeError("a real run needs a thread id")
        log = await context.github.open_issues(run_id, approved)
        log += append_regression_cases(approved, context.out_dir, run_id)
    return {"actions_log": log + await _remember(state, context, run_id)}


async def _remember(state: TriageState, context: TraceContext, run_id: str | None) -> list[str]:
    """Save the decided diagnoses to the known-issues memory; the log line, if any."""
    if context.known_issues is None:
        return []
    if run_id is None:  # the memory is keyed on the run: without one, nothing is saved
        logger.warning("known issues not saved: the run has no thread id")
        return []
    memories = issue_memories(
        state.get("clusters", []), state.get("diagnoses", []), state.get("decisions", {})
    )
    saved = await context.known_issues.save(state["target_app"], run_id, memories)
    return [f"remembered {saved} decided diagnosis(es) for later runs"] if saved else []
