"""collect_traces: the graph's first node. Reads failed-trace summaries through the trace client."""

from langgraph.runtime import Runtime

from agent.context import TraceContext
from agent.state import TriageState
from trace_store.models import FailedTraceQuery


async def collect_traces(state: TriageState, runtime: Runtime[TraceContext]) -> dict:
    """Fetch failed traces for the target app, optionally within a since/until window."""
    query = FailedTraceQuery.model_validate(
        {"app": state["target_app"], "since": state.get("since"), "until": state.get("until")}
    )
    found = await runtime.context.traces.search_failed_traces(query)
    # Plain dicts in state (JSON mode), so the checkpoint serializer has no models to warn about.
    return {"failed_traces": [t.model_dump(mode="json") for t in found]}
