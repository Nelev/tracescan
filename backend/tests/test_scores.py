"""runs.scores: the judge's verdicts as `scores` rows, and stored in Postgres (with
TEST_DATABASE_URL), where the trace browser's reader finds them."""

import pytest
from sqlalchemy import text

from runs.scores import EVALUATOR, ScoreStore, rows

FAILED = {
    "trace_id": "a" * 32,
    "failed": True,
    "score": 0.1,
    "blamed_span_id": "b" * 16,
    "reason": "patient John Doe",  # stands in for text that must never be stored
}
FINE = {"trace_id": "c" * 32, "failed": False, "score": 0.9, "blamed_span_id": None}


def test_each_verdict_is_one_row_of_ids_and_numbers():
    assert rows([FAILED, FINE]) == [
        {"trace_id": "a" * 32, "evaluator": EVALUATOR, "value": 0.1, "span_id": "b" * 16},
        {"trace_id": "c" * 32, "evaluator": EVALUATOR, "value": 0.9, "span_id": None},
    ]


async def stored(engine) -> list[tuple]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT trace_id, evaluator, value, span_id FROM scores ORDER BY trace_id")
        )
        return [tuple(row) for row in result]


@pytest.mark.anyio
async def test_a_later_verdict_replaces_the_judges_earlier_one(spans_engine):
    store = ScoreStore(spans_engine)
    assert await store.save([FAILED, FINE]) == 2
    # A later run finds the first trace went fine after all.
    assert await store.save([{**FAILED, "score": 0.8, "blamed_span_id": None}]) == 1
    assert await stored(spans_engine) == [
        ("a" * 32, EVALUATOR, 0.8, None),
        ("c" * 32, EVALUATOR, 0.9, None),
    ]


@pytest.mark.anyio
async def test_no_verdicts_write_nothing(spans_engine):
    assert await ScoreStore(spans_engine).save([]) == 0
    assert await stored(spans_engine) == []
