"""agent.chunks: the text a span is embedded as."""

from datetime import UTC, datetime, timedelta

import pytest

from agent.chunks import step_text
from trace_store.models import SpanNode

START = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
CLINICAL = "Jane Doe, 1957, metastatic"  # stands in for text that must never reach a chunk


def span(span_id, name, at, seconds, children=(), **fields) -> SpanNode:
    return SpanNode(
        span_id=span_id,
        trace_id="t1",
        name=name,
        start_time=START + timedelta(seconds=at),
        end_time=START + timedelta(seconds=at + seconds),
        status=fields.pop("status", "ok"),
        children=list(children),
        **fields,
    )


def medas_trace(tool_seconds: float = 10.2, failed: bool = True) -> SpanNode:
    """A request whose PubMed lookup timed out after an empty record search inside it.

    The children are stored out of order, to show the text follows start times.
    """
    search = span(
        "search",
        "retrieval record_chunks",
        at=1.1,
        seconds=0.2,
        attributes={"retrieval.hits": 0, "db.query.text": CLINICAL},
    )
    error = {
        "status": "error",
        "status_message": f"timed out looking up {CLINICAL}",
        "attributes": {"error.type": "httpx.ReadTimeout"},
    }
    tool = span(
        "tool",
        "execute_tool search_pubmed",
        1.0,
        tool_seconds,
        [search],
        **(error if failed else {}),
    )
    first = span("chat1", "chat gpt-x", at=0.0, seconds=0.9)
    second = span("chat2", "chat gpt-x", at=11.3, seconds=1.2)
    return span("root", "invoke_agent medas", 0.0, 12.6, [second, tool, first])


def test_a_failed_step_reads_as_its_error_type_its_neighbours_and_a_latency_word():
    assert step_text(medas_trace(), "tool") == (
        "step: execute_tool search_pubmed\n"
        "outcome: error httpx.ReadTimeout\n"
        "previous: chat gpt-x\n"
        "next: chat gpt-x\n"
        "inside: invoke_agent medas\n"
        "latency: very slow (>5 s)"
    )


def test_an_empty_retrieval_says_so():
    assert step_text(medas_trace(), "search") == (
        "step: retrieval record_chunks\n"
        "outcome: ok, hits: none\n"
        "previous: none\n"
        "next: none\n"
        "inside: execute_tool search_pubmed\n"
        "latency: fast (<0.5 s)"
    )


def test_a_healthy_and_a_failed_call_of_one_step_differ_only_in_outcome_and_latency():
    failed = step_text(medas_trace(), "tool").splitlines()
    healthy = step_text(medas_trace(tool_seconds=2.5, failed=False), "tool").splitlines()
    differ = [a.split(":")[0] for a, b in zip(failed, healthy, strict=True) if a != b]
    assert differ == ["outcome", "latency"]


def test_no_status_message_or_attribute_value_reaches_the_text():
    for span_id in ("root", "chat1", "tool", "search", "chat2"):
        text = step_text(medas_trace(), span_id)
        assert "Jane" not in text and "timed out" not in text


def test_a_redacted_count_is_left_out():
    tree = span("r", "retrieval record_chunks", 0, 0.1, attributes={"retrieval.hits": "[redacted]"})
    assert "outcome: ok\n" in step_text(tree, "r")


@pytest.mark.parametrize(("hits", "word"), [(0, "none"), (10, "some (1-10)"), (11, "many (>10)")])
def test_hit_counts_become_words(hits, word):
    tree = span("r", "retrieval record_chunks", 0, 0.1, attributes={"retrieval.hits": hits})
    assert f"hits: {word}" in step_text(tree, "r")


@pytest.mark.parametrize(
    ("seconds", "word"),
    [(0.49, "fast (<0.5 s)"), (0.5, "normal (0.5-2 s)"), (2.0, "slow (2-5 s)"),
     (5.0, "very slow (>5 s)")],
)  # fmt: skip
def test_durations_become_words(seconds, word):
    assert step_text(span("s", "execute_tool x", 0, seconds), "s").endswith(word)


def test_an_unknown_span_is_a_key_error():
    with pytest.raises(KeyError):
        step_text(medas_trace(), "nope")
