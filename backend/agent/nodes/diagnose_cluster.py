"""diagnose_cluster: one structured-output call per cluster.

The cluster's exemplar span trees go into the prompt next to the taxonomy, so the model needs no
tools of its own: the node fetches the trees, the model answers with a Diagnosis.
"""

import asyncio
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from agent.context import TraceContext
from agent.schemas import Cluster, ClusterTask, Diagnosis

logger = logging.getLogger(__name__)

TAXONOMY = (Path(__file__).parent.parent / "taxonomy.md").read_text()


async def diagnose_cluster(task: ClusterTask, runtime: Runtime[TraceContext]) -> dict:
    """Diagnose one cluster. A failure is recorded, not raised, so it cannot drop the others."""
    cluster = task["cluster"]
    try:
        diagnosis = await _diagnose(cluster, runtime.context)
    except Exception as exc:
        # Type name only: the message could carry span contents.
        logger.error("diagnosis of %s failed: %s", cluster["cluster_id"], type(exc).__name__)
        return {"diagnosis_failures": [cluster["cluster_id"]]}
    return {"diagnoses": [diagnosis]}


async def _diagnose(cluster: Cluster, context: TraceContext) -> dict:
    """Diagnose one cluster from its exemplar traces, citing their spans as evidence."""
    trees = await asyncio.gather(
        *(context.traces.get_trace_tree(trace_id) for trace_id in cluster["exemplar_trace_ids"])
    )
    prompt = (
        f"Cluster {cluster['cluster_id']}: {len(cluster['trace_ids'])} failed traces, most common "
        f"failure: {cluster['signature']}\n"
        "Cite only trace ids and span ids that appear in the exemplar traces below.\n"
        + "\n".join(tree.model_dump_json(exclude_defaults=True) for tree in trees)
    )
    # json_schema, not the default function_calling: that forces a tool_choice, which some models
    # (Claude through OpenRouter) reject with a 400.
    structured = context.model.with_structured_output(Diagnosis, method="json_schema")
    answer = await structured.ainvoke([SystemMessage(TAXONOMY), HumanMessage(prompt)])
    diagnosis = Diagnosis.model_validate(answer).model_dump(mode="json")
    # The cluster id is known, so the model does not get to name it.
    return {**diagnosis, "cluster_id": cluster["cluster_id"]}
