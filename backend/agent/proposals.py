"""
Turn clusters and their diagnoses into proposals: a markdown issue and a regression case each.
Pure and synchronous: no LangGraph, no model call, so it is testable offline.

The issue shows what a reviewer must weigh: confidence, how the evidence check went, how far the
cause was verified and how many traces the cluster rests on. Evidence is trace and span ids with
the diagnoser's note; no span attributes are copied. The regression case carries ids only.
"""

from agent.schemas import Cluster, Diagnosis, EvidenceCheck, Proposal, RegressionCase, SpanRef

TITLE_LIMIT = 80

UNVERIFIED_TEXT = "Unverified. The failure was not replayed; the cause comes from trace evidence."

# What the reviewer is told when the diagnoser's citations needed a second look; a clean check
# ("valid") says nothing.
EVIDENCE_CHECK_TEXT: dict[EvidenceCheck, str] = {
    "corrected": "Evidence check: corrected. The first answer cited spans it was not shown.",
    "unsupported": (
        "**Evidence check: unsupported.** The diagnoser kept citing spans it was not shown, so "
        "those were dropped and the confidence was capped. Read the traces before trusting this."
    ),
}


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _title(prefix: str, signature: str) -> str:
    title = f"[{prefix}] {_one_line(signature)}"
    return title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1] + "…"


def _traces_line(cluster: Cluster) -> str:
    if cluster["method"] == "isolated":
        return "1 failed trace that fits no group, so this rests on a single example."
    return f"{len(cluster['trace_ids'])} failed traces share this failure ({cluster['method']} cluster)."


def _issue(summary: list[str], evidence: str, cause: str, fix: str, verification: str) -> str:
    """The issue as markdown."""
    return (
        "## Summary\n\n" + "\n\n".join(summary) + "\n\n"
        f"## Evidence\n\n{evidence}\n\n"
        f"## Suspected cause\n\n{cause}\n\n"
        f"## Suggested fix\n\n{fix}\n\n"
        f"## Verification status\n\n{verification}\n"
    )


def _regression_case(cluster: Cluster, diagnosis: Diagnosis) -> RegressionCase:
    return RegressionCase(
        cluster_id=cluster["cluster_id"],
        signature=cluster["signature"],
        category=diagnosis.category,
        exemplar_trace_ids=cluster["exemplar_trace_ids"],
        failing_spans=[SpanRef(trace_id=e.trace_id, span_id=e.span_id) for e in diagnosis.evidence],
    )


def _diagnosed(cluster: Cluster, diagnosis: Diagnosis, evidence_check: EvidenceCheck) -> Proposal:
    summary = [
        f"`{cluster['signature']}`",
        _traces_line(cluster),
        f"Category: `{diagnosis.category}`. Confidence: {diagnosis.confidence:.0%}.",
    ]
    if check := EVIDENCE_CHECK_TEXT.get(evidence_check):
        summary.append(check)
    evidence = "\n".join(
        f"- trace `{e.trace_id}`, span `{e.span_id}`: {_one_line(e.note)}"
        for e in diagnosis.evidence
    )
    return Proposal(
        cluster_id=cluster["cluster_id"],
        title=_title(diagnosis.category, cluster["signature"]),
        body=_issue(
            summary, evidence, diagnosis.root_cause, diagnosis.suggested_fix, UNVERIFIED_TEXT
        ),
        diagnosed=True,
        regression_case=_regression_case(cluster, diagnosis),
    )


def _undiagnosed(cluster: Cluster) -> Proposal:
    exemplars = ", ".join(f"`{t}`" for t in cluster["exemplar_trace_ids"])
    summary = [f"`{cluster['signature']}`", _traces_line(cluster), "**No diagnosis.**"]
    return Proposal(
        cluster_id=cluster["cluster_id"],
        title=_title("undiagnosed", cluster["signature"]),
        body=_issue(
            summary,
            f"No evidence was cited. Exemplar traces to look at: {exemplars}.",
            "Not diagnosed: the model call failed or did not finish. A person needs to look.",
            "None proposed.",
            "Unverified. No cause was proposed, so there is nothing to verify.",
        ),
        diagnosed=False,
    )


def build_proposals(clusters: list[Cluster], diagnoses: list[dict]) -> list[Proposal]:
    """One proposal per cluster, in cluster order. A cluster without a diagnosis is not dropped.

    `diagnoses` are the dicts `diagnose_cluster` keeps in state: a `Diagnosis` plus `evidence_check`.
    """
    by_cluster = {d["cluster_id"]: d for d in diagnoses}
    proposals = []
    for cluster in clusters:
        stored = by_cluster.get(cluster["cluster_id"])
        if stored is None:
            proposals.append(_undiagnosed(cluster))
        else:
            diagnosis = Diagnosis.model_validate(stored)
            proposals.append(_diagnosed(cluster, diagnosis, stored["evidence_check"]))
    return proposals
