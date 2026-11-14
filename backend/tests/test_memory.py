"""agent.memory: what the known-issues memory keeps of a reviewed run."""

from agent.memory import issue_memories
from agent.schemas import Cluster, Decision


def cluster(cluster_id: str) -> Cluster:
    return Cluster(
        cluster_id=cluster_id,
        trace_ids=["t1"],
        signature=f"retrieve: {cluster_id}",
        exemplar_trace_ids=["t1"],
        method="step_error",
    )


def diagnosis(cluster_id: str, failing_step: str | None = "step: retrieve") -> dict:
    return {
        "cluster_id": cluster_id,
        "category": "retrieval_miss",
        "root_cause": f"cause of {cluster_id}",
        "suggested_fix": "fix it",
        "failing_step": failing_step,
    }


def test_approved_and_rejected_diagnoses_are_both_kept_with_their_verdict():
    memories = issue_memories(
        [cluster("c0"), cluster("c1")],
        [diagnosis("c1"), diagnosis("c0")],
        {"c0": "approve", "c1": "reject"},
    )
    assert [(m["cluster_id"], m["verdict"]) for m in memories] == [
        ("c0", "approved"),
        ("c1", "rejected"),
    ]
    assert memories[0] == {
        "cluster_id": "c0",
        "signature": "retrieve: c0",
        "verdict": "approved",
        "category": "retrieval_miss",
        "root_cause": "cause of c0",
        "suggested_fix": "fix it",
        "failing_step": "step: retrieve",
    }


def test_no_diagnosis_no_decision_or_no_failing_step_leaves_nothing():
    clusters = [cluster("undiagnosed"), cluster("undecided"), cluster("unblamed"), cluster("old")]
    diagnoses = [diagnosis("undecided"), diagnosis("unblamed", None), diagnosis("old")]
    del diagnoses[2]["failing_step"]  # a diagnosis from before the step was kept
    decisions: dict[str, Decision] = {
        "undiagnosed": "approve",
        "unblamed": "approve",
        "old": "reject",
    }
    assert issue_memories(clusters, diagnoses, decisions) == []
