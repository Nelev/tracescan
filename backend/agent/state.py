from typing import Required, TypedDict


class TriageState(TypedDict, total=False):
    target_app: Required[str]
    since: str  # ISO 8601 with timezone, inclusive; optional
    until: str  # ISO 8601 with timezone, exclusive; optional
    failed_traces: list[dict]
    clusters: list[dict]
    diagnoses: list[dict]
    reproductions: list[dict]
    known_matches: dict[str, str]
    proposals: list[dict]
    decisions: dict[str, str]
    actions_log: list[str]
