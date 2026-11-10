"""The run store: the same behaviour in memory and, when TEST_DATABASE_URL is set, in Postgres."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from db.engine import create_engine, sqlalchemy_url
from runs.store import NotClaimable, PostgresRunStore, RunCounts
from tests.fakes import InMemoryRunStore

SINCE = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "postgres"])
async def store(request):
    if request.param == "memory":
        yield InMemoryRunStore()
        return
    engine = create_engine(request.getfixturevalue("postgres_url"))
    async with engine.begin() as conn:  # the test database's own tables, emptied for each test
        await conn.execute(text("TRUNCATE reviews, runs, users"))
    yield PostgresRunStore(engine)
    await engine.dispose()


async def new_run(store, status="review_required", user: str | None = "ana") -> str:
    run_id = str(uuid4())
    await store.create_run(run_id, "medas", SINCE, None, status, user)
    return run_id


def test_the_checkpointers_url_becomes_a_psycopg_3_url():
    assert sqlalchemy_url("postgresql://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert sqlalchemy_url("postgres://u@h/d") == "postgresql+psycopg://u@h/d"
    assert sqlalchemy_url("postgresql+psycopg://u@h/d") == "postgresql+psycopg://u@h/d"


@pytest.mark.anyio
async def test_a_new_run_is_recorded_with_its_window_and_who_started_it(store):
    run_id = await new_run(store, "in_progress")
    run = await store.get_run(run_id)
    assert (run.run_id, run.target_app, run.status, run.started_by) == (
        run_id,
        "medas",
        "in_progress",
        "ana",
    )
    assert (run.since, run.until, run.ended_at) == (SINCE, None, None)
    assert (run.failed_traces, run.clusters, run.proposals) == (0, 0, 0)
    assert await store.get_run(str(uuid4())) is None


@pytest.mark.anyio
async def test_recording_a_run_again_leaves_it_as_it_is(store):
    run_id = await new_run(store, "in_progress")
    await store.create_run(run_id, "other", None, None, "failed", "bo")
    run = await store.get_run(run_id)
    assert (run.target_app, run.status, run.started_by) == ("medas", "in_progress", "ana")


@pytest.mark.anyio
async def test_runs_are_listed_newest_first_and_two_runs_share_one_user(store):
    first = await new_run(store)
    second = await new_run(store)
    nameless = await new_run(store, user=None)
    runs = await store.list_runs(10)
    assert [r.run_id for r in runs] == [nameless, second, first]
    assert [r.started_by for r in runs] == [None, "ana", "ana"]
    assert [r.run_id for r in await store.list_runs(2)] == [nameless, second]


@pytest.mark.anyio
async def test_an_ending_status_stamps_the_end_and_keeps_the_counts(store):
    run_id = await new_run(store, "in_progress")
    await store.set_status(run_id, "review_required", RunCounts(5, 2, 2))
    waiting = await store.get_run(run_id)
    assert waiting.status == "review_required" and waiting.ended_at is None
    assert (waiting.failed_traces, waiting.clusters, waiting.proposals) == (5, 2, 2)

    await store.set_status(run_id, "failed")
    failed = await store.get_run(run_id)
    assert failed.status == "failed" and failed.ended_at is not None
    assert (failed.failed_traces, failed.clusters, failed.proposals) == (5, 2, 2)
    await store.set_status(str(uuid4()), "failed")  # an unknown run: nothing to do, no error


DONE = RunCounts(2, 1, 1)


async def refused(store, run_id: str) -> bool:
    """Whether a review of the run is refused at the door."""
    try:
        async with store.reviewing(run_id, {"c0": "approve"}, "ana") as finish:
            await finish("completed", DONE)
    except NotClaimable:
        return True
    return False


@pytest.mark.anyio
async def test_a_review_keeps_its_decisions_and_the_status_it_ends_with(store):
    run_id = await new_run(store)
    async with store.reviewing(run_id, {"c1": "reject", "c0": "approve"}, "bo") as finish:
        await finish("completed", DONE)

    run = await store.get_run(run_id)
    assert run.status == "completed" and run.ended_at is not None
    assert (run.failed_traces, run.clusters, run.proposals) == (2, 1, 1)
    decided = await store.reviews(run_id)
    assert [(d.cluster_id, d.decision, d.reviewer) for d in decided] == [
        ("c0", "approve", "bo"),
        ("c1", "reject", "bo"),
    ]
    assert await refused(store, run_id)  # it ended: there is nothing left to review


@pytest.mark.anyio
async def test_a_run_held_by_one_review_refuses_a_second(store):
    run_id = await new_run(store)
    async with store.reviewing(run_id, {"c0": "reject"}, "bo") as finish:
        assert await refused(store, run_id)
        await finish("completed", DONE)
    assert [(d.decision, d.reviewer) for d in await store.reviews(run_id)] == [("reject", "bo")]


@pytest.mark.anyio
async def test_only_one_of_two_concurrent_reviews_gets_in(store):
    run_id = await new_run(store)

    async def review(decision: str, reviewer: str) -> bool:
        try:
            async with store.reviewing(run_id, {"c0": decision}, reviewer) as finish:
                await asyncio.sleep(0.05)  # the resume, while the other one arrives
                await finish("completed", DONE)
        except NotClaimable:
            return False
        return True

    assert sorted(await asyncio.gather(review("approve", "ana"), review("reject", "bo"))) == [
        False,
        True,
    ]
    assert len(await store.reviews(run_id)) == 1


@pytest.mark.anyio
async def test_a_review_that_fails_leaves_the_run_waiting_with_no_decision(store):
    run_id = await new_run(store)
    with pytest.raises(RuntimeError):
        async with store.reviewing(run_id, {"c0": "approve"}, "ana") as finish:
            await finish("completed", DONE)  # even a status already set is dropped
            raise RuntimeError("the resume failed")

    run = await store.get_run(run_id)
    assert run.status == "review_required" and run.ended_at is None
    assert await store.reviews(run_id) == []
    assert not await refused(store, run_id)  # and it can be reviewed again


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["completed", "failed", "aborted"])
async def test_a_run_that_ended_or_is_unknown_cannot_be_reviewed(store, status):
    run_id = await new_run(store, status)
    assert await refused(store, run_id)
    assert await refused(store, str(uuid4()))
    assert await store.reviews(run_id) == []


@pytest.mark.anyio
async def test_a_row_left_in_progress_can_be_reviewed(store):
    # The caller has seen in the checkpoint that the run waits; the row only missed that write.
    run_id = await new_run(store, "in_progress")
    assert not await refused(store, run_id)
