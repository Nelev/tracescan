"""Request and response bodies of the runs API. frontend/lib/types.ts mirrors them by hand.

`GET /v1/runs/{run_id}` returns `runs.RunStatus` as it is.
"""

from pydantic import AwareDatetime, BaseModel

from runs import Decision, RunState, RunSummary

# The response header that carries a paged list's total over all its pages (GET /v1/runs,
# GET /v1/traces), so the body stays a plain list for the callers that read only the first page.
TOTAL_COUNT = "X-Total-Count"


class RunRequest(BaseModel):
    target_app: str
    since: AwareDatetime | None = None  # inclusive
    until: AwareDatetime | None = None  # exclusive


class ReviewRequest(BaseModel):
    # One decision per proposal, keyed by cluster id; the run refuses a partial set.
    decisions: dict[str, Decision]


class ReviewResponse(BaseModel):
    status: RunState
    summary: RunSummary  # its actions_log says what was written, or would be in a dry run
