"""The trace judge's verdicts as `scores` rows, so the trace browser shows which traces failed.

One row per judged trace, evaluator `trace_judge`: the judge's score (0.0 failed its user, 1.0
went fine; the judge and the reader share one threshold, `trace_store.models.is_failed`) and the
span it blamed.
Ids and numbers only: the judge's reason is never stored. A later run's verdict on the same trace
replaces the earlier one.

Written for every run that ends or pauses at the review, without a person's approval, like the
healthy-span store: it holds no span content and never leaves the database.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from db.models import Score

EVALUATOR = "trace_judge"


class TraceScores(Protocol):
    async def save(self, verdicts: Sequence[Mapping]) -> int: ...


def rows(verdicts: Sequence[Mapping]) -> list[dict]:
    """One `scores` row per verdict. Pure."""
    return [
        {
            "trace_id": verdict["trace_id"],
            "evaluator": EVALUATOR,
            "value": verdict["score"],
            "span_id": verdict.get("blamed_span_id"),
        }
        for verdict in verdicts
    ]


class ScoreStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, verdicts: Sequence[Mapping]) -> int:
        """Store one score per verdict, replacing the judge's earlier one; returns how many."""
        values = rows(verdicts)
        if not values:
            return 0
        statement = insert(Score)
        statement = statement.on_conflict_do_update(
            index_elements=[Score.trace_id, Score.evaluator],
            set_={
                "value": statement.excluded.value,
                "span_id": statement.excluded.span_id,
                "scored_at": func.now(),
            },
        )
        async with self._engine.begin() as conn:
            await conn.execute(statement, values)
        return len(values)
