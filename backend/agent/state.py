from typing import TypedDict


class TriageState(TypedDict, total=False):
    target_app: str
    failed_traces: list[dict]
    clusters: list[dict]
    diagnoses: list[dict]
    reproductions: list[dict]
    known_matches: dict[str, str]
    proposals: list[dict]
    decisions: dict[str, str]
    actions_log: list[str]
