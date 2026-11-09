"""diagnose_cluster: one structured-output call per cluster, and a check of what it cites.

The cluster's exemplar span trees go into the prompt next to the taxonomy, so the model needs no
tools of its own: the node fetches the trees, the model answers with a Diagnosis. Every citation
must be a span of those trees. If one is not, the model is asked once more; if it still cites
spans it was not shown, those are dropped and the confidence is capped (see agent.evidence).
"""

import asyncio
import logging
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from agent.const import UNSUPPORTED_CONFIDENCE_CAP
from agent.context import TraceContext
from agent.evidence import (
    fallback_evidence,
    invalid_citations,
    keep_valid,
    retry_message,
    span_index,
)
from agent.schemas import Cluster, ClusterTask, Diagnosis, EvidenceCheck

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
    # One structured answer per call, so nobody reads tokens. Without this, a v3 event stream
    # routes the call through LangChain's token-streaming path; this keeps any injected model on
    # the same path as ainvoke.
    model = context.model.model_copy(update={"disable_streaming": True})
    structured = model.with_structured_output(Diagnosis, method="json_schema")

    async def ask(messages: list[BaseMessage]) -> Diagnosis:
        return Diagnosis.model_validate(await structured.ainvoke(messages))

    messages: list[BaseMessage] = [SystemMessage(TAXONOMY), HumanMessage(prompt)]
    diagnosis = await ask(messages)
    index = span_index(trees)
    bad = invalid_citations(diagnosis, index)
    check: EvidenceCheck = "valid"
    if bad:
        logger.warning(
            "diagnosis of %s cites %d span(s) it was not shown, asking again",
            cluster["cluster_id"],
            len(bad),
        )
        messages = [
            *messages,
            AIMessage(diagnosis.model_dump_json()),
            HumanMessage(retry_message(bad, index)),
        ]
        diagnosis = await ask(messages)
        bad = invalid_citations(diagnosis, index)
        check = "unsupported" if bad else "corrected"

    # The cluster id is known, so the model does not get to name it.
    result = {
        **diagnosis.model_dump(mode="json"),
        "cluster_id": cluster["cluster_id"],
        "evidence_check": check,
    }
    if check == "unsupported":
        # Keep the real citations; with none left, cite the cluster's own failing spans instead.
        kept = keep_valid(diagnosis, index) or fallback_evidence(trees)
        result["evidence"] = [e.model_dump(mode="json") for e in kept]
        result["confidence"] = min(diagnosis.confidence, UNSUPPORTED_CONFIDENCE_CAP)
    return result
