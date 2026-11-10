import os
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from agent import model_guard
from db.engine import create_engine
from main import app
from trace_store.postgres_reader import PostgresTraceReader, read_only_engine

BACKEND = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    """No test waits out a retry delay."""
    monkeypatch.setattr(model_guard, "RETRY_DELAY_S", 0)


@pytest.fixture
def postgres_url(monkeypatch) -> str:
    """TEST_DATABASE_URL, migrated to the newest revision; the test is skipped without it.

        docker run -d --name tracescan-test-db -e POSTGRES_PASSWORD=test \\
            -p 127.0.0.1:25440:5432 pgvector/pgvector:pg17
        TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:25440/postgres uv run pytest
    """
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run against Postgres")
    monkeypatch.setenv("DATABASE_URL", url)  # what migrations/env.py and the lifespan read
    monkeypatch.setenv("TRACE_DATABASE_URL", url)  # where the lifespan points the trace server
    config = Config()  # no ini file: this path is all an upgrade needs from it
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(config, "head")
    return url


@pytest.fixture
async def collector():
    """An HTTP client on the app, for POST /v1/traces."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
async def spans_engine(postgres_url):
    """The application's engine on empty `spans` and `scores`, also set as the app's engine."""
    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE spans, scores"))
    app.state.engine = engine
    yield engine
    del app.state.engine
    await engine.dispose()


@pytest.fixture
async def read_only(postgres_url, spans_engine):
    """The reader's own engine, on the emptied `spans` table."""
    engine = read_only_engine(postgres_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def reader(read_only):
    return PostgresTraceReader(read_only)
