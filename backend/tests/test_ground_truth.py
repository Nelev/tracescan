"""The eval's answer key: which seeded trace is of which kind, and what each kind really is."""

from collections import Counter

from api.traces import decode
from eval.ground_truth import FAULTS, NOT_FAULTS, cause_of
from eval.run import CONTROL_END, DEFAULT_END
from scripts.seed_traces import CONTROL_COUNTS, COUNTS, export, healthy, kinds
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


# Healthy traces the eval's day must have of each step a fault breaks, so a failure can be
# compared with the same step in a request that went fine.
HEALTHY_TWINS = 3


def test_the_eval_day_has_healthy_traces_that_ran_each_failing_step():
    traces = by_trace(decode(export(DEFAULT_END)))
    healthy_steps = Counter(
        name
        for trace_id, kind in kinds(DEFAULT_END).items()
        if kind == healthy.__name__
        for name in {span["name"] for span in traces[trace_id]}
    )

    for kind, fault in FAULTS.items():
        assert healthy_steps[fault.failing_span] >= HEALTHY_TWINS, kind


def test_the_control_day_has_no_fault_and_as_many_traces_as_an_eval_day():
    answer = kinds(CONTROL_END, CONTROL_COUNTS)
    assert set(answer.values()) <= NOT_FAULTS.keys()
    assert len(answer) == sum(COUNTS.values()) == sum(CONTROL_COUNTS.values())
    assert set(answer).isdisjoint(kinds(DEFAULT_END))


def test_a_shared_cause_names_a_fault_of_the_same_category_and_step_that_shares_none():
    shared = {kind: fault.same_cause_as for kind, fault in FAULTS.items() if fault.same_cause_as}
    assert shared == {"double_failure": "model_unavailable"}
    for kind, other in shared.items():
        assert FAULTS[other].same_cause_as is None  # one step, never a chain
        assert FAULTS[other].category == FAULTS[kind].category
        assert FAULTS[other].failing_span == FAULTS[kind].failing_span
        assert cause_of(kind) == other
    assert cause_of("source_timeout") == "source_timeout"
    assert cause_of("healthy") == "healthy"
