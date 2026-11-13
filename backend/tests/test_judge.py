"""judge_trace against a fake chat model, so no model is ever called."""

import json

import pytest

from agent import model_guard
from agent.const import MAX_MODEL_ATTEMPTS
from agent.judge import JUDGE_PROMPT, fallback_span, healthy_picks, judge_trace
from agent.model_guard import Spent
from agent.schemas import TraceVerdict
from tests.fakes import FakeApiError, span_tree
from tests.fakes import scripted_model as scripted

# A root that failed because the tool below it failed; a retrieval that worked.
TREE = span_tree(
    "t1",
    span_id="root",
    name="invoke_agent medas",
    children=[
        span_tree("t1", span_id="tool", parent_span_id="root", name="execute_tool lookup"),
        span_tree(
            "t1",
            span_id="search",
            parent_span_id="root",
            name="retrieval record_chunks",
            status="ok",
            start_time="2026-11-05T10:00:00.5Z",
        ),
    ],
)
FAILED = TraceVerdict(
    reason="The lookup tool failed.", score=0.1, blamed_span_id="tool", attribution="app"
)
FINE = TraceVerdict(reason="Every step worked.", score=0.9)
# A request where every step worked and the retrieval found records.
CLEAN = span_tree(
    "t2",
    span_id="root",
    status="ok",
    children=[
        span_tree("t2", span_id="chat", parent_span_id="root", status="ok"),
        span_tree(
            "t2",
            span_id="search",
            parent_span_id="root",
            status="ok",
            attributes={"retrieval.hits": 4},
        ),
    ],
)


@pytest.mark.anyio
async def test_a_failed_trace_blames_the_span_the_model_named():
    model, spent = scripted(FAILED), Spent()
    verdict = await judge_trace(TREE, model, spent)
    json.dumps(verdict)  # plain JSON, ready for graph state
    assert verdict == {
        "trace_id": "t1",
        "failed": True,
        "score": 0.1,
        "reason": "The lookup tool failed.",
        "blamed_span_id": "tool",
        "blame_check": "valid",
        "attribution": "app",
        "healthy_span_ids": [],
    }
    assert spent == Spent(calls=1, tokens=150, cost_usd=0.001)


@pytest.mark.anyio
async def test_a_trace_with_an_error_span_gives_no_references():
    # Judged fine, but a span failed: a retry or a reported failure is not a clean example.
    fine = FINE.model_copy(update={"healthy_span_ids": ["search"]})
    verdict = await judge_trace(TREE, scripted(fine), Spent())
    assert verdict["healthy_span_ids"] == []


@pytest.mark.anyio
async def test_healthy_picks_keep_only_spans_of_a_clean_tree():
    # The root, an unknown id and a repeat are dropped.
    picks = ["search", "root", "made-up", "search", "chat"]
    fine = FINE.model_copy(update={"healthy_span_ids": picks})
    verdict = await judge_trace(CLEAN, scripted(fine), Spent())
    assert verdict["healthy_span_ids"] == ["search", "chat"]


def test_a_borderline_fine_gives_no_references():
    assert healthy_picks(CLEAN, ["search"], score=0.6) == []


def test_a_retrieval_that_found_nothing_gives_no_references():
    # silent_no_hits: no error anywhere, but the answer has no records behind it.
    chat, search = CLEAN.children
    empty = CLEAN.model_copy(
        update={"children": [chat, search.model_copy(update={"attributes": {"retrieval.hits": 0}})]}
    )
    assert healthy_picks(empty, ["chat"], score=1.0) == []


@pytest.mark.anyio
async def test_a_failed_trace_keeps_no_healthy_picks():
    failed = FAILED.model_copy(update={"healthy_span_ids": ["search"]})
    verdict = await judge_trace(TREE, scripted(failed), Spent())
    assert verdict["healthy_span_ids"] == []


def test_healthy_picks_stop_at_the_cap():
    tree = span_tree(
        "t1",
        span_id="root",
        status="ok",
        children=[
            span_tree("t1", span_id=f"s{i}", parent_span_id="root", status="ok") for i in range(5)
        ],
    )
    assert healthy_picks(tree, [f"s{i}" for i in range(5)], score=1.0) == ["s0", "s1", "s2"]


@pytest.mark.anyio
async def test_the_model_sees_the_prompt_and_the_tree():
    model = scripted(FINE)
    await judge_trace(TREE, model, Spent())
    (messages,) = model.seen
    assert messages[0].content == JUDGE_PROMPT
    assert '"span_id":"search"' in str(messages[1].content)


@pytest.mark.anyio
async def test_a_trace_that_went_fine_blames_nothing_even_if_the_model_names_a_span():
    verdict = await judge_trace(
        TREE, scripted(FINE.model_copy(update={"blamed_span_id": "tool"})), Spent()
    )
    assert (verdict["failed"], verdict["blamed_span_id"], verdict["blame_check"]) == (
        False,
        None,
        None,
    )


@pytest.mark.anyio
async def test_an_unknown_span_is_asked_again_with_the_valid_ids():
    wrong = FAILED.model_copy(update={"blamed_span_id": "made-up"})
    model, spent = scripted(wrong, FAILED), Spent()
    verdict = await judge_trace(TREE, model, spent)
    assert (verdict["blamed_span_id"], verdict["blame_check"]) == ("tool", "corrected")
    assert spent.calls == 2
    retry = str(model.seen[1][-1].content)
    assert "made-up" in retry and "root, search, tool" in retry


@pytest.mark.anyio
async def test_still_unknown_after_the_retry_blames_the_deepest_error_span():
    wrong = FAILED.model_copy(update={"blamed_span_id": None})
    verdict = await judge_trace(TREE, scripted(wrong), Spent())
    assert (verdict["blamed_span_id"], verdict["blame_check"]) == ("tool", "fallback")


@pytest.mark.anyio
async def test_no_retry_without_budget():
    wrong = FAILED.model_copy(update={"blamed_span_id": "made-up"})
    model, spent = scripted(wrong), Spent(calls=MAX_MODEL_ATTEMPTS - 1)
    verdict = await judge_trace(TREE, model, spent)
    assert len(model.seen) == 1
    assert (verdict["blamed_span_id"], verdict["blame_check"]) == ("tool", "fallback")


@pytest.mark.anyio
async def test_a_retry_that_changes_its_mind_counts_as_not_failed():
    wrong = FAILED.model_copy(update={"blamed_span_id": "made-up"})
    verdict = await judge_trace(TREE, scripted(wrong, FINE), Spent())
    assert (verdict["failed"], verdict["blamed_span_id"], verdict["blame_check"]) == (
        False,
        None,
        None,
    )


@pytest.mark.anyio
async def test_a_model_error_is_raised_and_still_counted():
    spent = Spent()
    with pytest.raises(FakeApiError):
        await judge_trace(TREE, scripted(FakeApiError(503)), spent)
    assert spent.calls == 1


def test_fallback_span_is_the_deepest_error_or_the_root():
    assert fallback_span(TREE) == "tool"
    healthy = span_tree("t2", span_id="only", status="ok")
    assert fallback_span(healthy) == "only"


@pytest.mark.anyio
async def test_a_failed_trace_keeps_the_models_attribution():
    external = FAILED.model_copy(update={"attribution": "external"})
    verdict = await judge_trace(TREE, scripted(external), Spent())
    assert verdict["attribution"] == "external"


@pytest.mark.anyio
async def test_a_failed_trace_with_no_attribution_is_unclear():
    verdict = await judge_trace(
        TREE, scripted(FAILED.model_copy(update={"attribution": None})), Spent()
    )
    assert verdict["attribution"] == "unclear"


@pytest.mark.anyio
async def test_a_trace_that_went_fine_has_no_attribution_even_if_the_model_gives_one():
    verdict = await judge_trace(
        TREE, scripted(FINE.model_copy(update={"attribution": "app"})), Spent()
    )
    assert verdict["attribution"] is None


@pytest.mark.anyio
async def test_the_re_ask_keeps_to_the_trace_budget_not_the_clusters(monkeypatch):
    monkeypatch.setattr(model_guard, "MAX_TRACE_TOKENS", 100)  # the first call alone costs 150
    wrong = FAILED.model_copy(update={"blamed_span_id": "made-up"})
    model = scripted(wrong, FAILED)
    verdict = await judge_trace(TREE, model, Spent())
    assert len(model.seen) == 1
    assert verdict["blame_check"] == "fallback"
