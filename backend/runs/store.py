"""The record of runs beside the checkpoints: which runs exist, how each ended, who decided what.

`RunStore` is what `runs.Runs` needs; `PostgresRunStore` keeps it in the tables of db.models.
Tests use the in-memory one in tests/fakes.py, so they need no database.

Rows hold ids, counts and decisions, never issue text or span content.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Update, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from agent.schemas import Decision
from db.models import Review, Run, User
from db.models import RunStatus as StoredStatus

ENDED: frozenset[str] = frozenset({"completed", "failed", "aborted"})
# What a review may take. `in_progress` too: the checkpoint has already shown that the run waits
# for review, so such a row is only one whose last status write was lost.
CLAIMABLE: frozenset[str] = frozenset({"review_required", "in_progress"})


class NotClaimable(Exception):
    """The run is not there to review: unknown, ended, or held by another review right now."""


@dataclass(frozen=True)
class RunCounts:
    failed_traces: int
    clusters: int
    proposals: int


# Ends a review: sets where the run stands after it, in the review's own transaction.
Finish = Callable[[StoredStatus, RunCounts], Awaitable[None]]


class RunRecord(BaseModel):
    """One row of `runs`, with the starter's name."""

    run_id: str
    target_app: str
    since: datetime | None
    until: datetime | None
    status: StoredStatus
    started_by: str | None  # a user's name; None for a run first recorded at its review
    created_at: datetime
    ended_at: datetime | None
    failed_traces: int
    clusters: int
    proposals: int


class ReviewRecord(BaseModel):
    cluster_id: str
    decision: Decision
    reviewer: str
    decided_at: datetime


class RunStore(Protocol):
    async def create_run(
        self,
        run_id: str,
        target_app: str,
        since: datetime | None,
        until: datetime | None,
        status: StoredStatus,
        user: str | None,
    ) -> None:
        """Record a run. A run that is already recorded is left as it is."""
        ...

    async def set_status(
        self, run_id: str, status: StoredStatus, counts: RunCounts | None = None
    ) -> None:
        """Set the status, and the counts when given. An ending status also sets `ended_at`."""
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

    async def list_runs(self, limit: int) -> list[RunRecord]:
        """The newest runs first."""
        ...


# The columns of a RunRecord, under its field names.
_SELECT_RUNS = select(
    Run.id.label("run_id"),
    Run.target_app,
    Run.since,
    Run.until,
    Run.status,
    User.name.label("started_by"),
    Run.created_at,
    Run.ended_at,
    Run.failed_traces,
    Run.clusters,
    Run.proposals,
).join(User, Run.started_by == User.id, isouter=True)


def _record(row) -> RunRecord:
    return RunRecord(**{**row._mapping, "run_id": str(row.run_id)})


def _set_status(run_id: str, status: StoredStatus, counts: RunCounts | None) -> Update:
    values: dict = {"status": status}
    if status in ENDED:
        values["ended_at"] = func.now()
    if counts is not None:
        values |= asdict(counts)
    return update(Run).where(Run.id == UUID(run_id)).values(**values)


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

    async def _user_id(self, conn: AsyncConnection, name: str) -> UUID:
        """The id of the user of that name, created when new."""
        # DO UPDATE, not DO NOTHING, so the existing row's id is returned too.
        upsert = (
            pg_insert(User)
            .values(id=uuid4(), name=name)
            .on_conflict_do_update(index_elements=[User.name], set_={"name": name})
            .returning(User.id)
        )
        return (await conn.execute(upsert)).scalar_one()

    async def create_run(
        self,
        run_id: str,
        target_app: str,
        since: datetime | None,
        until: datetime | None,
        status: StoredStatus,
        user: str | None,
    ) -> None:
        async with self._engine.begin() as conn:
            started_by = await self._user_id(conn, user) if user else None
            await conn.execute(
                pg_insert(Run)
                .values(
                    id=UUID(run_id),
                    target_app=target_app,
                    since=since,
                    until=until,
                    status=status,
                    started_by=started_by,
                )
                .on_conflict_do_nothing(index_elements=[Run.id])
            )

    async def set_status(
        self, run_id: str, status: StoredStatus, counts: RunCounts | None = None
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(_set_status(run_id, status, counts))

    @asynccontextmanager
    async def reviewing(
        self, run_id: str, decisions: Mapping[str, Decision], reviewer: str
    ) -> AsyncIterator[Finish]:
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
                reviewer_id = await self._user_id(conn, reviewer)
                await conn.execute(
                    insert(Review),
                    [
                        {
                            "run_id": UUID(run_id),
                            "cluster_id": cluster_id,
                            "decision": decision,
                            "reviewer_id": reviewer_id,
                        }
                        for cluster_id, decision in decisions.items()
                    ],
                )

            async def finish(status: StoredStatus, counts: RunCounts) -> None:
                await conn.execute(_set_status(run_id, status, counts))

            yield finish

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(_SELECT_RUNS.where(Run.id == UUID(run_id)))).first()
        return _record(row) if row else None

    async def list_runs(self, limit: int) -> list[RunRecord]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(_SELECT_RUNS.order_by(Run.created_at.desc()).limit(limit))
            return [_record(row) for row in rows]

    async def reviews(self, run_id: str) -> list[ReviewRecord]:
        """The run's recorded decisions, by cluster id. Nothing in the app reads them yet."""
        query = (
            select(Review.cluster_id, Review.decision, User.name, Review.decided_at)
            .join(User, Review.reviewer_id == User.id)
            .where(Review.run_id == UUID(run_id))
            .order_by(Review.cluster_id)
        )
        async with self._engine.connect() as conn:
            return [
                ReviewRecord(
                    cluster_id=row.cluster_id,
                    decision=row.decision,
                    reviewer=row.name,
                    decided_at=row.decided_at,
                )
                for row in await conn.execute(query)
            ]
