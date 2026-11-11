"""diagnose_cluster: one structured-output call per cluster, and a check of what it cites.

The cluster's exemplar span trees go into the prompt next to the taxonomy, so the model needs no
tools of its own: the node fetches the trees, the model answers with a Diagnosis. Every citation
must be a span of those trees. If one is not, the model is asked once more; if it still cites
spans it was not shown, those are dropped and the confidence is capped (see agent.evidence).

Each run is one attempt, with a budget check before and after (agent.model_guard). The budget is
the cluster's `model_usage` entries in graph state, which the router passes in the task. A
transient model error with budget left leaves the cluster unfinished: the run returns only its
usage entry and the graph runs the node again. Without budget the cluster is recorded as failed.
The evidence re-ask draws on the same budget; when it is spent the diagnosis is kept as
`unsupported`, never dropped.
"""

import asyncio
import logging
from dataclasses import asdict
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
from agent.model_guard import Spent, backoff_delay, retryable, spent_for, structured_asker
from agent.schemas import Cluster, ClusterTask, Diagnosis, EvidenceCheck

logger = logging.getLogger(__name__)

TAXONOMY = (Path(__file__).parent.parent / "taxonomy.md").read_text()


async def diagnose_cluster(state: ClusterTask, runtime: Runtime[TraceContext]) -> dict:
    """Diagnose one cluster. A failure is recorded, not raised, so it cannot drop the others.

    `state` is the Send payload, not the graph state: LangGraph's node type fixes the name.
    """
    cluster = state["cluster"]
    cluster_id = cluster["cluster_id"]
    before = spent_for(state.get("model_usage", []), cluster_id)
    if not before.ok():
        # The router sends a cluster again only while it has budget, so this is a safeguard.
        logger.error("diagnosis of %s: model budget already spent, not running", cluster_id)
        return {"diagnosis_failures": [cluster_id]}
    if before.calls:  # a re-run after a transient error: wait first
        await asyncio.sleep(backoff_delay(before.calls))

    run = Spent()  # this run only; the state keeps the sum of all runs
    try:
        diagnosis = await _diagnose(cluster, runtime.context, before, run)
    except Exception as exc:
        usage = {"model_usage": [{"cluster_id": cluster_id, **asdict(run)}]}
        # No verdict yet if a call made in this run hit a transient error and budget is left.
        # `run.calls` matters: a failure before any call (a trace fetch) would never use up the
        # budget, and the graph would run the node again for ever.
        if run.calls and retryable(exc) and (before + run).ok():
            logger.warning("diagnosis of %s: %s, will run again", cluster_id, type(exc).__name__)
            return usage
        # Type name only: the message could carry span contents.
        logger.error("diagnosis of %s failed: %s", cluster_id, type(exc).__name__)
        return {"diagnosis_failures": [cluster_id], **usage}
    return {
        "diagnoses": [diagnosis],
        "model_usage": [{"cluster_id": cluster_id, **asdict(run)}],
    }


async def _diagnose(cluster: Cluster, context: TraceContext, before: Spent, run: Spent) -> dict:
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
    ask = structured_asker(context.model, Diagnosis, run)
    messages: list[BaseMessage] = [SystemMessage(TAXONOMY), HumanMessage(prompt)]
    diagnosis = await ask(messages)
    index = span_index(trees)
    bad = invalid_citations(diagnosis, index)
    check: EvidenceCheck = "valid"
    if bad:
        check = "unsupported"  # what it stays when the budget is spent: kept, not dropped
        if (before + run).ok():
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
