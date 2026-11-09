"""The lifespan checkpoints into Postgres. Runs only when TEST_DATABASE_URL is set.

    docker run -d --name tracescan-test-db -e POSTGRES_PASSWORD=test -p 127.0.0.1:25440:5432 \
        pgvector/pgvector:pg17
    TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:25440/postgres uv run pytest
"""

import os
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig

from agent.context import TraceContext
from main import app
from tests.fakes import FakeTraces, HashingEmbedder, summary

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="set TEST_DATABASE_URL to run against Postgres")
@pytest.mark.anyio
async def test_run_state_survives_restarting_the_app(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid4())}}
    context = TraceContext(FakeTraces([summary("t1")]), HashingEmbedder())
    async with app.router.lifespan_context(app):
        await app.state.graph.ainvoke({"target_app": "medas"}, config, context=context)

    async with app.router.lifespan_context(app):  # new connection, as after a restart
        snapshot = await app.state.graph.aget_state(config)
    assert [row["trace_id"] for row in snapshot.values["failed_traces"]] == ["t1"]
