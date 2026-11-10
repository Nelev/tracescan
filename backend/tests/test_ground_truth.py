"""The eval's answer key: which seeded trace is of which kind, and what each kind really is."""

from collections import Counter

from api.traces import decode
from eval.ground_truth import FAULTS
from scripts.seed_traces import COUNTS, export, healthy, kinds
from tests.test_seed_traces import END, by_trace
from trace_store.postgres_reader import origin

SEEDED = {make.__name__: count for make, count in COUNTS.items()}


def test_every_seeded_trace_has_a_kind_and_the_kinds_add_up():
    answer = kinds(END)

    assert set(answer) == set(by_trace(decode(export(END))))
    assert Counter(answer.values()) == SEEDED
    assert kinds(END) == answer  # worked out again, the same


def test_every_seeded_failure_has_an_answer_and_healthy_has_none():
    assert set(FAULTS) == set(SEEDED) - {healthy.__name__}


def test_a_trace_of_a_kind_fails_where_its_answer_says():
    traces = by_trace(decode(export(END)))
    for trace_id, kind in kinds(END).items():
        errors = [span for span in traces[trace_id] if span["status"] == "error"]
        if kind in FAULTS:
            # The same rule the reader uses to name the failing span of a trace.
            assert origin(errors)["name"] == FAULTS[kind].failing_span, kind
        else:
            assert errors == []
