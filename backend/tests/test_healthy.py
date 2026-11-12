"""runs.healthy: the judge's healthy picks as documents, and stored in Postgres (with
TEST_DATABASE_URL), embedded by an offline stand-in so no model is downloaded."""

import pytest
from sqlalchemy import text

from agent.const import CHUNK_TEMPLATE_VERSION, EMBEDDING_DIMENSIONS
from db.engine import create_engine
from runs.healthy import HealthyStore, documents
from tests.fakes import HashingEmbedder

PICK = {"span_id": "s1", "step": "execute_tool search_pubmed", "text": "step: x\noutcome: ok"}
VERDICTS = [
    {"trace_id": "t1", "failed": False, "healthy_spans": [PICK]},
    {"trace_id": "t2", "failed": True, "healthy_spans": []},
    {"trace_id": "t3", "failed": False},  # a verdict from before the picks
]


def test_each_pick_is_one_document_with_its_filters_and_a_stable_id():
    (doc,) = documents("medas", VERDICTS)
    assert doc.id == f"t1:s1:v{CHUNK_TEMPLATE_VERSION}"
    assert doc.page_content == PICK["text"]
    assert doc.metadata == {
        "app": "medas",
        "trace_id": "t1",
        "span_id": "s1",
        "step": "execute_tool search_pubmed",
        "v": CHUNK_TEMPLATE_VERSION,
    }


@pytest.fixture
async def engine(postgres_url):
    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        # PGVector creates its tables on first use; start each test from no rows.
        await conn.execute(
            text("DROP TABLE IF EXISTS langchain_pg_embedding, langchain_pg_collection")
        )
    yield engine
    await engine.dispose()


async def rows(engine) -> list[str]:
    async with engine.connect() as conn:
        return list((await conn.execute(text("SELECT id FROM langchain_pg_embedding"))).scalars())


@pytest.mark.anyio
async def test_saving_a_window_again_replaces_its_rows(engine):
    store = HealthyStore(engine, HashingEmbedder(EMBEDDING_DIMENSIONS))
    assert await store.save("medas", VERDICTS) == 1
    # A second store, as after a restart, on the same rows.
    await HealthyStore(engine, HashingEmbedder(EMBEDDING_DIMENSIONS)).save("medas", VERDICTS)
    assert await rows(engine) == [f"t1:s1:v{CHUNK_TEMPLATE_VERSION}"]


@pytest.mark.anyio
async def test_no_picks_write_nothing(engine):
    store = HealthyStore(engine, HashingEmbedder(EMBEDDING_DIMENSIONS))
    assert await store.save("medas", VERDICTS[1:]) == 0
