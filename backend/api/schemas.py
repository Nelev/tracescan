"""Request and response bodies of the runs API. frontend/lib/types.ts mirrors them by hand.

`GET /v1/runs/{run_id}` returns `runs.RunStatus` as it is.
"""

from pydantic import AwareDatetime, BaseModel, field_validator, model_validator

from runs import Decision, RunState, RunSummary
from trace_store.const import ALLOWED_APPS

# The response header that carries a paged list's total over all its pages (GET /v1/runs,
# GET /v1/traces), so the body stays a plain list for the callers that read only the first page.
TOTAL_COUNT = "X-Total-Count"
# The largest `offset` a paged list takes (GET /v1/runs, GET /v1/traces): far past any real list,
# and well inside the bigint Postgres compares it with, so a huge one is a 422, not a 500.
MAX_OFFSET = 1_000_000


class RunRequest(BaseModel):
    """What a run is over; refused with a 422 before it starts (and before it counts against the
    run limit) for an app the trace store does not serve or a window that ends before it starts."""

    target_app: str
    since: AwareDatetime | None = None  # inclusive
    until: AwareDatetime | None = None  # exclusive

    @field_validator("target_app")
    @classmethod
    def _served(cls, app: str) -> str:
        if app not in ALLOWED_APPS:
            raise ValueError(f"not an app this server reads: one of {sorted(ALLOWED_APPS)}")
        return app

    @model_validator(mode="after")
    def _window(self) -> "RunRequest":
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError("the window must end after it starts")
        return self


class ReviewRequest(BaseModel):
    # One decision per proposal, keyed by cluster id; the run refuses a partial set.
    decisions: dict[str, Decision]


class ReviewResponse(BaseModel):
    status: RunState
    summary: RunSummary  # its actions_log says what was written, or would be in a dry run
