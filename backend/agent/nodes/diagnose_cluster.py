"""diagnose_cluster: one structured-output call per cluster, and a check of what it cites.

The cluster's exemplar span trees go into the prompt next to the taxonomy, so the model needs no
tools of its own: the node fetches the trees, the model answers with a Diagnosis. Every citation
must be a span of those trees. If one is not, the model is asked once more; if it still cites
spans it was not shown, those are dropped and the confidence is capped (see agent.evidence).

A transient model error is retried call by call (`retrying` in agent.model_guard), after a
doubling wait, while the cluster's budget has room; any other error, or one with no budget left,
records the cluster in `diagnosis_failures`. The evidence re-ask draws on the same budget; when it is spent the
diagnosis is kept as `unsupported`, never dropped. The retries live in the node, not in the
graph: a run is durable only once it waits for review, so nothing is gained by checkpointing them.

With a healthy-span store in the context, the prompt also gets the nearest healthy calls of the
failing step (`healthy_twins`), as comparison only: they are not spans of the exemplars, so the
evidence check would refuse a citation of them.
"""

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from agent.chunks import step_text
from agent.const import HEALTHY_TWINS, UNSUPPORTED_CONFIDENCE_CAP
from agent.context import TraceContext
from agent.evidence import (
    fallback_evidence,
    invalid_citations,
    keep_valid,
    retry_message,
    span_index,
)
from agent.model_guard import Spent, cluster_budget, retrying, structured_asker
from agent.schemas import Cluster, ClusterTask, Diagnosis, EvidenceCheck
from trace_store.models import SpanNode

logger = logging.getLogger(__name__)

TAXONOMY = (Path(__file__).parent.parent / "taxonomy.md").read_text()


async def diagnose_cluster(state: ClusterTask, runtime: Runtime[TraceContext]) -> dict:
    """Diagnose one cluster. A failure is recorded, not raised, so it cannot drop the others.

    `state` is the Send payload, not the graph state: LangGraph's node type fixes the name.
    """
    cluster = state["cluster"]
    cluster_id = cluster["cluster_id"]
    context = runtime.context
    spent = Spent()  # every call, failed ones included
    try:
        # Per-run cap, see TraceContext.diagnose_slots.
        async with context.diagnose_slots:
            # Fetched once: a failing fetch is a failure, not a model error to retry.
            trees = await asyncio.gather(
                *(context.traces.get_trace_tree(t) for t in cluster["exemplar_trace_ids"])
            )
            twins = await healthy_twins(state, trees, context)
            diagnosis = await _diagnose(cluster, trees, context.model, spent, twins)
    except Exception as exc:
        # Type name only: the message could carry span contents.
        logger.error("diagnosis of %s failed: %s", cluster_id, type(exc).__name__)
        return {"diagnosis_failures": [cluster_id], **_usage(cluster_id, spent)}
    return {"diagnoses": [diagnosis], **_usage(cluster_id, spent)}


async def healthy_twins(task: ClusterTask, trees: list[SpanNode], context: TraceContext) -> str:
    """The prompt section with healthy calls of the cluster's failing step, or "" when there are
    none. The step is the one the trace judge blamed in the first exemplar that has one; the
    query is that span's step_text. Best effort: a failing lookup leaves the section out."""
    blamed = task["failing_span"]
    if context.healthy is None or blamed is None:
        return ""
    trace_id, span_id = blamed["trace_id"], blamed["span_id"]
    try:
        tree = next(tree for tree in trees if tree.trace_id == trace_id)
        failed = step_text(tree, span_id)
        twins = await context.healthy.similar(
            failed, blamed["step"], task["target_app"], HEALTHY_TWINS
        )
    except Exception as exc:
        logger.warning(
            "healthy twins of %s not found: %s", task["cluster"]["cluster_id"], type(exc).__name__
        )
        return ""
    if not twins:
        return ""
    return (
        f"\nThe failing step of exemplar {trace_id}, span {span_id}:\n{failed}\n"
        "Healthy calls of the same step from requests that went fine, nearest first. Compare "
        "them with the failure to find what differs. They are not evidence: do not cite them.\n"
        + "\n---\n".join(twin.text for twin in twins)
        + "\n"
    )


def _usage(cluster_id: str, spent: Spent) -> dict:
    return {"model_usage": [{"cluster_id": cluster_id, **asdict(spent)}]}


async def _diagnose(
    cluster: Cluster, trees: list[SpanNode], model: BaseChatModel, spent: Spent, twins: str
) -> dict:
    """One attempt: diagnose the cluster from its exemplar trees, citing their spans as evidence."""
    prompt = (
        f"Cluster {cluster['cluster_id']}: {len(cluster['trace_ids'])} failed traces, most common "
        f"failure: {cluster['signature']}\n"
        "Cite only trace ids and span ids that appear in the exemplar traces below.\n"
        + "\n".join(tree.model_dump_json(exclude_defaults=True) for tree in trees)
        + twins
    )
    budget = cluster_budget()
    ask = retrying(
        structured_asker(model, Diagnosis, spent),
        spent,
        budget,
        f"diagnosis of {cluster['cluster_id']}",
    )
    messages: list[BaseMessage] = [SystemMessage(TAXONOMY), HumanMessage(prompt)]
    diagnosis = await ask(messages)
    index = span_index(trees)
    bad = invalid_citations(diagnosis, index)
    check: EvidenceCheck = "valid"
    if bad:
        check = "unsupported"  # what it stays when the budget is spent: kept, not dropped
        if spent.ok(budget):
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
