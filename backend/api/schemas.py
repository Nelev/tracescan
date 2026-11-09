"""Request and response bodies of the runs API. frontend/lib/types.ts mirrors them by hand."""

from pydantic import AwareDatetime, BaseModel


class RunRequest(BaseModel):
    target_app: str
    since: AwareDatetime | None = None  # inclusive
    until: AwareDatetime | None = None  # exclusive


class RunResponse(BaseModel):
    run_id: str  # the graph's thread_id
    failed_traces: int
    clusters: int
    unclustered: int  # failures that fit no cluster; kept, not diagnosed
    diagnoses: int
    diagnosis_failures: int  # clusters whose diagnosis failed; reported, not dropped
    proposals: int
    actions_log: list[str]
