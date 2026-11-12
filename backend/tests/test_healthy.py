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


def verdict(trace_id: str, step: str, latency: str) -> dict:
    text = f"step: {step}\noutcome: ok\nlatency: {latency}"
    return {"trace_id": trace_id, "healthy_spans": [{"span_id": "s", "step": step, "text": text}]}


@pytest.mark.anyio
async def test_similar_finds_the_nearest_calls_of_the_same_step_only(engine):
    store = HealthyStore(engine, HashingEmbedder(EMBEDDING_DIMENSIONS))
    pubmed, medline = "execute_tool search_pubmed", "execute_tool search_medlineplus"
    await store.save(
        "medas",
        [
            verdict("fast", pubmed, "fast (<0.5 s)"),
            verdict("slow", pubmed, "slow (2-5 s)"),
            verdict("other_step", medline, "slow (2-5 s)"),
        ],
    )
    await store.save("other_app", [verdict("other_app", pubmed, "slow (2-5 s)")])

    query = f"step: {pubmed}\noutcome: error TimeoutError\nlatency: slow (2-5 s)"
    found = await store.similar(query, pubmed, "medas", k=5)
    assert [match.trace_id for match in found] == ["slow", "fast"]
    assert found[0].distance < found[1].distance and found[0].text.endswith("slow (2-5 s)")


@pytest.mark.anyio
async def test_similar_finds_nothing_for_a_step_with_no_healthy_calls(engine):
    store = HealthyStore(engine, HashingEmbedder(EMBEDDING_DIMENSIONS))
    await store.save("medas", VERDICTS)
    assert await store.similar("step: x", "execute_tool never_seen", "medas", 3) == []
