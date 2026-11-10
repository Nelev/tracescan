"""apply_actions: the graph's only writing node. It acts on approved proposals and nothing else."""

from langgraph.runtime import Runtime

from agent.actions import require_dry_run, write_dry_run
from agent.context import TraceContext
from agent.schemas import Proposal
from agent.state import TriageState


def apply_actions(state: TriageState, runtime: Runtime[TraceContext]) -> dict:
    """Write the issue and the regression case of every approved proposal.

    A dry run writes local files (agent.actions). The real writers (GitHub, the eval dataset, the
    known-issues store) are not built, so a run with `dry_run` off fails here, before any write.
    """
    context = runtime.context
    require_dry_run(context.dry_run)
    decisions = state.get("decisions", {})
    approved = [
        Proposal.model_validate(p)
        for p in state.get("proposals", [])
        if decisions.get(p["cluster_id"]) == "approve"
    ]
    return {"actions_log": write_dry_run(approved, context.out_dir)}
