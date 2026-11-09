"""What a diagnosis may cite: only spans of the traces the diagnoser was shown."""

from agent.evidence import (
    FALLBACK_NOTE,
    fallback_evidence,
    invalid_citations,
    keep_valid,
    retry_message,
    span_index,
)
from agent.schemas import Evidence
from tests.fakes import DIAGNOSIS, span_tree


def citing(*pairs: tuple[str, str]):
    return DIAGNOSIS.model_copy(
        update={"evidence": [Evidence(trace_id=t, span_id=s, note="x") for t, s in pairs]}
    )


def nested(trace_id: str, *, error_in_child: bool):
    """root (ok or error) -> a -> b (error when error_in_child)."""
    grandchild = span_tree(trace_id, span_id=f"{trace_id}_b", status="error")
    child = span_tree(trace_id, span_id=f"{trace_id}_a", status="ok", children=[grandchild])
    root_status = "ok" if error_in_child else "error"
    return span_tree(trace_id, status=root_status, children=[child])


def test_the_index_walks_nested_children_and_keeps_traces_apart():
    index = span_index([nested("t1", error_in_child=True), span_tree("t2")])
    assert index == {"t1": {"t1_root", "t1_a", "t1_b"}, "t2": {"t2_root"}}


def test_citing_spans_that_were_shown_is_fine():
    index = span_index([span_tree("t1", span_id="s1")])
    assert invalid_citations(citing(("t1", "s1")), index) == []


def test_an_unknown_trace_is_caught():
    index = span_index([span_tree("t1", span_id="s1")])
    (bad,) = invalid_citations(citing(("t9", "s1")), index)
    assert (bad.trace_id, bad.span_id) == ("t9", "s1")


def test_an_unknown_span_in_a_known_trace_is_caught():
    index = span_index([span_tree("t1", span_id="s1")])
    (bad,) = invalid_citations(citing(("t1", "s2")), index)
    assert bad.span_id == "s2"


def test_a_span_counts_only_under_its_own_trace():
    index = span_index([span_tree("t1"), span_tree("t2")])
    assert len(invalid_citations(citing(("t1", "t2_root")), index)) == 1


def test_keep_valid_drops_only_the_fake_citations():
    index = span_index([span_tree("t1", span_id="s1")])
    kept = keep_valid(citing(("t1", "s1"), ("t9", "s9")), index)
    assert [(e.trace_id, e.span_id) for e in kept] == [("t1", "s1")]


def test_the_fallback_cites_the_first_failing_span_of_each_trace_else_its_root():
    trees = [nested("t1", error_in_child=True), span_tree("t2", status="ok")]
    cited = [(e.trace_id, e.span_id) for e in fallback_evidence(trees)]
    assert cited == [("t1", "t1_b"), ("t2", "t2_root")]
    assert {e.note for e in fallback_evidence(trees)} == {FALLBACK_NOTE}


def test_the_retry_message_names_the_bad_citations_and_every_valid_span():
    index = span_index([span_tree("t1", span_id="s1")])
    bad = invalid_citations(citing(("t9", "s9")), index)
    message = retry_message(bad, index)
    assert "t9/s9" in message
    assert "t1: s1" in message
