"""The eval's answer key: which seeded trace is of which kind, and what each kind really is."""

from collections import Counter

from api.traces import decode
from eval.ground_truth import FAULTS, NOT_FAULTS
from scripts.seed_traces import COUNTS, export, healthy, kinds
from tests.test_seed_traces import END, by_trace

SEEDED = {make.__name__: count for make, count in COUNTS.items()}


def test_every_seeded_trace_has_a_kind_and_the_kinds_add_up():
    answer = kinds(END)

    assert set(answer) == set(by_trace(decode(export(END))))
    assert Counter(answer.values()) == SEEDED
    assert kinds(END) == answer  # worked out again, the same


def test_every_seeded_kind_is_a_fault_or_is_said_not_to_be_one():
    assert set(FAULTS).isdisjoint(NOT_FAULTS)
    assert set(FAULTS) | set(NOT_FAULTS) == set(SEEDED)


def test_a_trace_of_a_kind_fails_where_its_answer_says():
    traces = by_trace(decode(export(END)))
    for trace_id, kind in kinds(END).items():
        spans = traces[trace_id]
        errors = [span for span in spans if span["status"] == "error"]
        if kind == healthy.__name__ or (kind in FAULTS and FAULTS[kind].silent):
            assert errors == [], kind
        if kind in FAULTS:
            # Among the error spans with no error span below them (one, but for a request
            # with two errors); for a failure with no error, among all the spans.
            parents = {span["parent_span_id"] for span in errors}
            starts = [span["name"] for span in errors if span["span_id"] not in parents]
            assert FAULTS[kind].failing_span in (starts or [span["name"] for span in spans]), kind
