"""The scoring job: what each check says about a trace, and that stored traces get scored once."""

import pytest
from sqlalchemy import text

from api.traces import decode, store_spans
from scripts.seed_traces import export, kinds
from tests.test_seed_traces import END, by_trace
from trace_store.scoring import BAD, score_trace

# Per seeded kind (scripts/seed_traces.py): the checks that score it bad. None for a request
# that worked, with or without an error span in it.
LOW = {
    "healthy": set(),
    "source_timeout": {"timeout"},
    "tight_timeout": {"timeout"},
    "tool_arguments": {"tool_schema_error"},
    "model_unavailable": {"request_failed"},
    "context_overflow": {"request_failed"},
    "unexplained": {"request_failed"},
    "store_down": {"request_failed", "tool_error"},
    "double_failure": {"request_failed", "timeout"},
    "silent_no_hits": {"empty_retrieval"},  # no span failed
    "retried_ok": set(),  # the failed call was tried again and worked
    "not_found": set(),  # an expected error
}


def test_each_seeded_kind_is_scored_bad_by_the_checks_that_fit_it_and_no_other():
    traces = by_trace(decode(export(END)))
    answer = kinds(END)
    assert set(answer.values()) == set(LOW)

    for trace_id, kind in answer.items():
        scores = score_trace(traces[trace_id])
        assert {name for name, (value, _) in scores.items() if value == BAD} == LOW[kind], kind
        assert "request_failed" in scores  # every trace has at least this score


def test_every_bad_score_blames_the_span_the_failure_is_in():
    traces = by_trace(decode(export(END)))
    names = {span["span_id"]: span["name"] for spans in traces.values() for span in spans}

    blamed = {
        (kind, check): names.get(span_id)
        for trace_id, kind in kinds(END).items()
        for check, (value, span_id) in score_trace(traces[trace_id]).items()
        if value == BAD
    }

    assert blamed[("silent_no_hits", "empty_retrieval")] == "retrieval record_chunks"
    assert blamed[("source_timeout", "timeout")] == "execute_tool search_pubmed"
    assert blamed[("tool_arguments", "tool_schema_error")] == "execute_tool export_conversation"
    # A failed request blames the span the failure started in, not the root.
    assert blamed[("model_unavailable", "request_failed")] == "chat openai/gpt-4.1-mini"
    assert blamed[("store_down", "request_failed")] == "retrieval record_chunks"
    assert blamed[("unexplained", "request_failed")] == "invoke_agent medas"  # nothing below it


@pytest.mark.anyio
async def test_stored_traces_are_scored_once_and_a_trace_without_its_root_is_not(spans_engine):
    rows = decode(export(END))
    root_of_one = next(row for row in rows if row["parent_span_id"] is None)
    late = [row for row in rows if row["trace_id"] == root_of_one["trace_id"]]
    first = [row for row in rows if row not in late]

    async def scored() -> tuple[int, int]:
        async with spans_engine.connect() as conn:
            counts = await conn.execute(
                text("SELECT count(DISTINCT trace_id), count(*) FROM scores")
            )
            return tuple(counts.one())

    await store_spans(spans_engine, first + [row for row in late if row is not root_of_one])
    traces, scores = await scored()
    assert traces == len(kinds(END)) - 1  # the trace whose root has not arrived waits

    await store_spans(spans_engine, [root_of_one])
    assert (await scored())[0] == len(kinds(END))

    before = await scored()
    await store_spans(spans_engine, rows)  # an exporter's retry
    assert await scored() == before
