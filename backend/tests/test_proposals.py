"""Proposals: the issue and regression case drafted for each cluster, offline and without a model."""

import json

import pytest

from agent.graph import build_graph
from agent.proposals import TITLE_LIMIT, build_proposals
from agent.schemas import Cluster, Proposal
from tests.fakes import (
    DIAGNOSIS,
    FakeTraces,
    fake_context,
    fake_diagnoser,
    span_tree,
    summary,
)

SECTIONS = [
    "## Summary",
    "## Evidence",
    "## Suspected cause",
    "## Suggested fix",
    "## Verification status",
]
PHI = "patient John Doe"  # stands in for clinical text in span attributes

CLUSTER = Cluster(
    cluster_id="c0",
    trace_ids=["t1", "t2", "t3"],
    signature="retrieve: empty result",
    exemplar_trace_ids=["t1", "t2"],
    method="step_error",
)
ISOLATED = Cluster(
    cluster_id="c1",
    trace_ids=["t9"],
    signature="generate: context length exceeded",
    exemplar_trace_ids=["t9"],
    method="isolated",
)


def diagnosis(cluster_id: str = "c0", **overrides) -> dict:
    """A stored diagnosis, as diagnose_cluster puts it into state."""
    return {
        **DIAGNOSIS.model_dump(mode="json"),
        "cluster_id": cluster_id,
        "evidence_check": "valid",
        **overrides,
    }


def only(clusters: list[Cluster], diagnoses: list[dict]) -> Proposal:
    (proposal,) = build_proposals(clusters, diagnoses)
    return proposal


def test_a_diagnosed_cluster_gets_a_full_issue():
    proposal = only([CLUSTER], [diagnosis()])
    assert proposal.diagnosed and proposal.verification == "unverified"
    assert proposal.title == "[retrieval_miss] retrieve: empty result"
    positions = [proposal.body.index(heading) for heading in SECTIONS]
    assert positions == sorted(positions)  # all five sections, in order
    assert "3 failed traces share this failure (step_error cluster)" in proposal.body
    assert "Confidence: 70%" in proposal.body
    assert "trace `t1`, span `s1`: retrieve returned nothing" in proposal.body
    assert "The retriever's filter excludes the drug-interaction category." in proposal.body
    assert "Include the category in the filter." in proposal.body
    assert "Unverified" in proposal.body


def test_a_diagnosed_cluster_gets_a_regression_case_of_ids_only():
    case = only([CLUSTER], [diagnosis()]).regression_case
    assert case is not None
    assert case.model_dump(mode="json") == {
        "cluster_id": "c0",
        "signature": "retrieve: empty result",
        "category": "retrieval_miss",
        "exemplar_trace_ids": ["t1", "t2"],
        "failing_spans": [{"trace_id": "t1", "span_id": "s1"}],
        "run_id": None,  # stamped when it is written (agent.actions)
    }


def test_a_cluster_without_a_diagnosis_still_gets_a_proposal():
    proposal = only([CLUSTER], [])
    assert not proposal.diagnosed and proposal.regression_case is None
    assert proposal.title.startswith("[undiagnosed]")
    assert all(heading in proposal.body for heading in SECTIONS)
    assert "No diagnosis" in proposal.body
    assert "`t1`, `t2`" in proposal.body  # where the reviewer should look


def test_there_is_one_proposal_per_cluster_in_cluster_order():
    proposals = build_proposals([CLUSTER, ISOLATED], [diagnosis("c1", category="model_quality")])
    assert [(p.cluster_id, p.diagnosed) for p in proposals] == [("c0", False), ("c1", True)]


def test_an_isolated_cluster_says_it_rests_on_one_trace():
    proposal = only([ISOLATED], [diagnosis("c1")])
    assert "single example" in proposal.body


@pytest.mark.parametrize("check", ["valid", "corrected", "unsupported"])
def test_the_evidence_check_is_shown_unless_it_was_clean(check):
    body = only([CLUSTER], [diagnosis(evidence_check=check)]).body
    assert (f"Evidence check: {check}" in body) == (check != "valid")


def test_a_long_signature_is_cut_in_the_title_only():
    cluster = Cluster({**CLUSTER, "signature": "retrieve: " + "very long error " * 20})
    proposal = only([cluster], [diagnosis()])
    assert len(proposal.title) == TITLE_LIMIT and proposal.title.endswith("…")
    assert cluster["signature"] in proposal.body  # the body keeps all of it


@pytest.mark.anyio
async def test_the_graph_drafts_a_proposal_per_cluster_without_copying_span_attributes():
    failures = [
        summary("t1", failing_span_name="retrieve", error_message="empty result"),
        summary("t2", failing_span_name="generate", error_message="context length exceeded"),
    ]
    trees = {t: span_tree(t, attributes={"patient": PHI}) for t in ("t1", "t2")}
    context = fake_context(FakeTraces(failures, trees), fake_diagnoser(DIAGNOSIS))
    result = await build_graph().ainvoke({"target_app": "medas"}, context=context)

    proposals = result["proposals"]
    assert [p["cluster_id"] for p in proposals] == [c["cluster_id"] for c in result["clusters"]]
    assert PHI not in json.dumps(proposals)
