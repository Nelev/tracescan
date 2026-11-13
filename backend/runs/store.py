"""The record of runs beside the checkpoints: which runs exist, how each ended, who decided what.

`RunStore` is what `runs.Runs` needs; `PostgresRunStore` keeps it in the tables of db.models.
Tests use the in-memory one in tests/fakes.py, so they need no database.

Rows hold ids, counts and decisions, never issue text or span content.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable, Collection, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import Update, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from agent.schemas import Decision
from db.models import Review, Run
from db.models import RunStatus as StoredStatus
from runs.schemas import ReviewRecord, RunCounts, RunRecord

ENDED: frozenset[str] = frozenset({"completed", "failed", "aborted"})
# What a review may take. `in_progress` too: the checkpoint has already shown that the run waits
# for review, so such a row is only one whose last status write was lost.
CLAIMABLE: frozenset[str] = frozenset({"review_required", "in_progress"})
# A run that stopped before it ended (only the store knows it): what a resume may take back.
RESUMABLE: frozenset[str] = frozenset({"failed", "aborted"})
# The only status a run's own stream may move: once a run waits for review, ended, or was taken
# by a review or a resume, a late write from the stream must change nothing.
RUNNING: frozenset[str] = frozenset({"in_progress"})


class NotClaimable(Exception):
    """The run is not there to review or resume: unknown, in another state, or held by another
    review or resume right now."""


# Ends a review: sets where the run stands after it, in the review's own transaction.
Finish = Callable[[StoredStatus, RunCounts], Awaitable[None]]


class RunStore(Protocol):
    async def create_run(
        self,
        run_id: str,
        target_app: str,
        since: datetime | None,
        until: datetime | None,
        status: StoredStatus,
        user: str,
    ) -> None:
        """Record a run. A run that is already recorded is left as it is."""
        ...

    async def set_status(
        self,
        run_id: str,
        status: StoredStatus,
        counts: RunCounts | None = None,
        only_from: Collection[str] | None = None,
    ) -> bool:
        """Set the status, and the counts when given; return whether the run changed. An ending
        status sets `ended_at`, any other clears it (a resumed run is running again).

        With `only_from`, only a run whose status is one of those changes; any other is left as
        it is, so a write that arrives late cannot undo one that came first, and of two writes
        from the same status (two resumes) only one changes the run.
        """
        ...

    async def record_decisions(
        self, run_id: str, decisions: Mapping[str, Decision], reviewer: str
    ) -> None:
        """Record decisions that are already in the checkpoint, outside a review: those of a review
        whose apply failed after the graph had taken them. A decision already recorded is kept."""
        ...

    def reviewing(
        self, run_id: str, decisions: Mapping[str, Decision], reviewer: str
    ) -> AbstractAsyncContextManager[Finish]:
        """Hold the run for one review: record its decisions, apply it inside, then call `finish`.

        Entering raises `NotClaimable` when the run is not there to review; of two concurrent
        reviews only one gets in. The decisions and the status `finish` sets are kept together
        when the block ends, and dropped together when it raises or the process dies, so a review
        that was not applied leaves the run waiting for review, with no decision recorded.
        """
        ...

    async def get_run(self, run_id: str) -> RunRecord | None: ...

    async def list_runs(self, limit: int, offset: int = 0) -> list[RunRecord]:
        """The newest runs first, skipping the first `offset` of them (one page of the list)."""
        ...

    async def count_runs(self) -> int:
        """How many runs are recorded: the length of the whole list, for its pages."""
        ...


# The columns of a RunRecord, under its field names.
_SELECT_RUNS = select(
    Run.id.label("run_id"),
    Run.target_app,
    Run.since,
    Run.until,
    Run.status,
    Run.started_by,
    Run.created_at,
    Run.ended_at,
    Run.failed_traces,
    Run.clusters,
    Run.proposals,
)


def _record(row) -> RunRecord:
    return RunRecord(**{**row._mapping, "run_id": str(row.run_id)})


def _set_status(
    run_id: str,
    status: StoredStatus,
    counts: RunCounts | None,
    only_from: Collection[str] | None = None,
) -> Update:
    values: dict = {"status": status, "ended_at": func.now() if status in ENDED else None}
    if counts is not None:
        values |= asdict(counts)
    query = update(Run).where(Run.id == UUID(run_id))
    if only_from is not None:
        # Checked again after waiting on a row lock (READ COMMITTED), so a write that waited
        # behind a review sees the review's status, not the one before it.
        query = query.where(Run.status.in_(only_from))
    return query.values(**values).returning(Run.id)


def _review_rows(run_id: str, decisions: Mapping[str, Decision], reviewer: str) -> list[dict]:
    return [
        {
            "run_id": UUID(run_id),
            "cluster_id": cluster_id,
            "decision": decision,
            "reviewer": reviewer,
        }
        for cluster_id, decision in decisions.items()
    ]


class PostgresRunStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def check(self) -> None:
        """Fail now, with the command to run, if the tables are missing."""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(select(Run.id).limit(1))
        except Exception as exc:
            raise RuntimeError(
                "the runs table cannot be read: run `uv run alembic upgrade head`"
            ) from exc

    async def create_run(
        self,
        run_id: str,
        target_app: str,
        since: datetime | None,
        until: datetime | None,
        status: StoredStatus,
        user: str,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                pg_insert(Run)
                .values(
                    id=UUID(run_id),
                    target_app=target_app,
                    since=since,
                    until=until,
                    status=status,
                    started_by=user,
                )
                .on_conflict_do_nothing(index_elements=[Run.id])
            )

    async def set_status(
        self,
        run_id: str,
        status: StoredStatus,
        counts: RunCounts | None = None,
        only_from: Collection[str] | None = None,
    ) -> bool:
        async with self._engine.begin() as conn:
            changed = await conn.execute(_set_status(run_id, status, counts, only_from))
            return changed.first() is not None

    async def record_decisions(
        self, run_id: str, decisions: Mapping[str, Decision], reviewer: str
    ) -> None:
        if not decisions:
            return
        async with self._engine.begin() as conn:
            await conn.execute(
                pg_insert(Review)
                .values(_review_rows(run_id, decisions, reviewer))
                .on_conflict_do_nothing(index_elements=[Review.run_id, Review.cluster_id])
            )

    @asynccontextmanager
    async def reviewing(
        self, run_id: str, decisions: Mapping[str, Decision], reviewer: str
    ) -> AsyncGenerator[Finish]:
        # One transaction for the whole review. It holds a row lock on the run, so a second
        # review skips the row and is refused; a failure or a dead process rolls it all back.
        async with self._engine.begin() as conn:
            held = await conn.execute(
                select(Run.id)
                .where(Run.id == UUID(run_id), Run.status.in_(CLAIMABLE))
                .with_for_update(skip_locked=True)
            )
            if held.first() is None:
                raise NotClaimable
            if decisions:
                await conn.execute(insert(Review), _review_rows(run_id, decisions, reviewer))

            async def finish(status: StoredStatus, counts: RunCounts) -> None:
                await conn.execute(_set_status(run_id, status, counts))

            yield finish

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(_SELECT_RUNS.where(Run.id == UUID(run_id)))).first()
        return _record(row) if row else None

    async def list_runs(self, limit: int, offset: int = 0) -> list[RunRecord]:
        # The id breaks ties, so two runs created in the same instant keep one order across pages.
        newest_first = _SELECT_RUNS.order_by(Run.created_at.desc(), Run.id)
        async with self._engine.connect() as conn:
            rows = await conn.execute(newest_first.limit(limit).offset(offset))
            return [_record(row) for row in rows]

    async def count_runs(self) -> int:
        async with self._engine.connect() as conn:
            return (await conn.execute(select(func.count()).select_from(Run))).scalar_one()

    async def reviews(self, run_id: str) -> list[ReviewRecord]:
        """The run's recorded decisions, by cluster id. Nothing in the app reads them yet."""
        query = (
            select(Review.cluster_id, Review.decision, Review.reviewer, Review.decided_at)
            .where(Review.run_id == UUID(run_id))
            .order_by(Review.cluster_id)
        )
        async with self._engine.connect() as conn:
            return [
                ReviewRecord(
                    cluster_id=row.cluster_id,
                    decision=row.decision,
                    reviewer=row.reviewer,
                    decided_at=row.decided_at,
                )
                for row in await conn.execute(query)
            ]
