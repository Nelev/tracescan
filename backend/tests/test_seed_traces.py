"""The seed script: its export is whole traces the collector decodes and the reader can serve."""

from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from api.traces import decode, store_spans
from scripts import seed_traces as seed
from scripts.seed_traces import COUNTS, DAY, export
from trace_store.models import FailedTraceQuery

END = datetime(2026, 11, 10, 12, tzinfo=UTC)
FAILED = sum(COUNTS.values()) - COUNTS[seed.healthy]


def by_trace(rows):
    traces = {}
    for row in rows:
        traces.setdefault(row["trace_id"], []).append(row)
    return traces


def test_the_export_decodes_into_whole_traces_within_the_day():
    rows = decode(export(END))
    traces = by_trace(rows)

    assert len(traces) == sum(COUNTS.values())
    for spans in traces.values():
        ids = {span["span_id"] for span in spans}
        roots = [span for span in spans if span["parent_span_id"] is None]
        assert len(roots) == 1 and roots[0]["name"] == "invoke_agent medas"
        assert all(span["parent_span_id"] in ids for span in spans if span not in roots)
        assert all(END - DAY <= span["start_time"] <= span["end_time"] < END for span in spans)


def test_a_failed_span_carries_its_exception_type_and_a_healthy_trace_has_none():
    traces = by_trace(decode(export(END)))
    failed = [s for s in traces.values() if any(span["status"] == "error" for span in s)]

    assert len(failed) == FAILED
    for spans in failed:
        for span in (span for span in spans if span["status"] == "error"):
            (event,) = span["events"]
            assert event["name"] == "exception"
            assert event["attributes"]["exception.type"] == span["attributes"]["error.type"]
            assert span["status_message"] == event["attributes"]["exception.message"]


def test_the_same_end_gives_the_same_export_and_another_end_other_traces():
    rows = decode(export(END))
    next_day = decode(export(END + timedelta(days=1)))

    assert decode(export(END)) == rows
    assert {row["trace_id"] for row in rows}.isdisjoint(row["trace_id"] for row in next_day)


@pytest.mark.anyio
async def test_seeded_failures_are_what_the_reader_finds(spans_engine, reader):
    rows = decode(export(END))
    assert await store_spans(spans_engine, rows) == len(rows)
    assert await store_spans(spans_engine, rows) == 0  # a second run stores nothing new

    found = await reader.search_failed_traces(FailedTraceQuery(app="medas", limit=100))

    assert Counter(summary.signature for summary in found) == {
        "execute_tool search_pubmed httpx.ReadTimeout": COUNTS[seed.source_timeout],
        "execute_tool export_conversation pydantic_core._pydantic_core.ValidationError": COUNTS[
            seed.tool_arguments
        ],
        "chat openai/gpt-4.1-mini openai.InternalServerError": COUNTS[seed.model_unavailable],
        "chat openai/gpt-4.1-mini openai.BadRequestError": COUNTS[seed.context_overflow],
        "retrieval record_chunks sqlalchemy.exc.OperationalError": COUNTS[seed.store_down],
    }
