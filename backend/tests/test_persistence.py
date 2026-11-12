"""The lifespan checkpoints into Postgres. Runs only when TEST_DATABASE_URL is set: the command
that starts a database for it is on the `postgres_url` fixture in conftest.py.
"""

from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig

from main import app
from tests.fakes import FakeTraces, fake_context, summary


@pytest.mark.anyio
async def test_run_state_survives_restarting_the_app(monkeypatch, postgres_url):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")  # the lifespan builds the model only
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_placeholder")  # read, never used here
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid4())}}
    context = fake_context(FakeTraces([summary("t1")]))
    async with app.router.lifespan_context(app):
        await app.state.graph.ainvoke({"target_app": "medas"}, config, context=context)

    async with app.router.lifespan_context(app):  # new connection, as after a restart
        snapshot = await app.state.graph.aget_state(config)
    assert [row["trace_id"] for row in snapshot.values["failed_traces"]] == ["t1"]
