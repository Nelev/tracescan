"""collect_traces: the graph's first node. Lists every trace in the window through the trace client.

Which of them failed is the trace judge's call (score_trace), not the trace store's.
"""

from langgraph.runtime import Runtime

from agent.const import MAX_JUDGED_TRACES
from agent.context import TraceContext
from agent.state import TriageState
from trace_store.models import TraceQuery


async def collect_traces(state: TriageState, runtime: Runtime[TraceContext]) -> dict:
    """Fetch the target app's traces, optionally within a since/until window, newest first."""
    query = TraceQuery.model_validate(
        {
            "app": state["target_app"],
            "since": state.get("since"),
            "until": state.get("until"),
            "limit": MAX_JUDGED_TRACES,
        }
    )
    found = await runtime.context.traces.search_traces(query)
    # Plain dicts in state (JSON mode), so the checkpoint serializer has no models to warn about.
    return {"traces": [t.model_dump(mode="json") for t in found]}
