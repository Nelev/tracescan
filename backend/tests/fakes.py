"""Test doubles shared by the graph and API tests."""

from trace_store.models import FailedTraceQuery, TraceSummary


class FakeTraces:
    def __init__(self, found: list[TraceSummary] | None = None) -> None:
        self.found = found or []
        self.queries: list[FailedTraceQuery] = []

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        self.queries.append(query)
        return self.found


def summary(trace_id: str) -> TraceSummary:
    return TraceSummary.model_validate(
        {
            "trace_id": trace_id,
            "app": "medas",
            "start_time": "2026-11-05T10:00:00Z",
            "duration_ms": 120.0,
            "status": "error",
            "signature": "retrieve: empty result",
        }
    )
