"""draft_proposals: one issue and regression case per cluster. No model call; see agent.proposals."""

from agent.proposals import build_proposals
from agent.state import TriageState


def draft_proposals(state: TriageState) -> dict:
    """Draft the proposals the reviewer will approve or reject, as plain dicts."""
    proposals = build_proposals(state.get("clusters", []), state.get("diagnoses", []))
    return {"proposals": [p.model_dump(mode="json") for p in proposals]}
