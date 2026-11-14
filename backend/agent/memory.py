"""What the known-issues memory keeps of a reviewed run: one IssueMemory per decided, diagnosed
proposal. Pure: apply_actions builds them, the store (runs.known_issues) embeds and saves them.

Approved and rejected diagnoses are both kept: an approved one as a confirmed cause, a rejected one
as a warning for the diagnoser. A rejected one is never used to match or suppress an issue.
A cluster with no diagnosis, or whose trace judge blamed no span (no failing step to embed),
leaves nothing.
"""

from collections.abc import Mapping, Sequence

from agent.schemas import Cluster, Decision, IssueMemory, IssueVerdict

VERDICT: dict[Decision, IssueVerdict] = {"approve": "approved", "reject": "rejected"}


def issue_memories(
    clusters: Sequence[Cluster], diagnoses: Sequence[Mapping], decisions: Mapping[str, Decision]
) -> list[IssueMemory]:
    """One memory per cluster that has a decision, a diagnosis and a failing step, in cluster
    order."""
    by_cluster = {d["cluster_id"]: d for d in diagnoses}
    memories = []
    for cluster in clusters:
        cluster_id = cluster["cluster_id"]
        diagnosis = by_cluster.get(cluster_id)
        decision = decisions.get(cluster_id)
        if diagnosis is None or decision is None or not diagnosis.get("failing_step"):
            continue
        memories.append(
            IssueMemory(
                cluster_id=cluster_id,
                signature=cluster["signature"],
                verdict=VERDICT[decision],
                category=diagnosis["category"],
                root_cause=diagnosis["root_cause"],
                suggested_fix=diagnosis["suggested_fix"],
                failing_step=diagnosis["failing_step"],
            )
        )
    return memories
