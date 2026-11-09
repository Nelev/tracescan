from typing import Required, TypedDict

from agent.schemas import Cluster


class TriageState(TypedDict, total=False):
    target_app: Required[str]
    since: str  # ISO 8601 with timezone, inclusive; optional
    until: str  # ISO 8601 with timezone, exclusive; optional
    failed_traces: list[dict]
    clusters: list[Cluster]
    # Trace ids that fit no cluster, even after regrouping the noise. Kept, but not diagnosed.
    unclustered: list[str]
    diagnoses: list[dict]
    reproductions: list[dict]
    known_matches: dict[str, str]
    proposals: list[dict]
    decisions: dict[str, str]
    actions_log: list[str]
