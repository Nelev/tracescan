"""runs.known_issues: decided diagnoses as documents, and stored in Postgres (with
TEST_DATABASE_URL), embedded by an offline stand-in so no model is downloaded."""

import pytest
from langchain_core.documents import Document
from sqlalchemy import text

from agent.const import CHUNK_TEMPLATE_VERSION, EMBEDDING_DIMENSIONS
from agent.schemas import IssueMemory, IssueVerdict
from db.engine import create_engine
from runs.known_issues import KnownIssueStore, documents, near, same_app
from tests.fakes import HashingEmbedder


def memory(
    cluster_id: str, verdict: IssueVerdict = "approved", step="step: retrieve\noutcome: ok"
) -> IssueMemory:
    return IssueMemory(
        cluster_id=cluster_id,
        signature="retrieve: empty result",
        verdict=verdict,
        category="retrieval_miss",
        root_cause=f"cause of {cluster_id}",
        suggested_fix="fix it",
        failing_step=step,
    )


def test_each_memory_is_one_document_embedding_its_failing_step_only():
    (doc,) = documents("medas", "run-1", [memory("c0", "rejected")])
    assert doc.id == f"medas:run-1:c0:v{CHUNK_TEMPLATE_VERSION}"
    assert doc.page_content == "step: retrieve\noutcome: ok"
    assert doc.metadata == {
        "app": "medas",
        "v": CHUNK_TEMPLATE_VERSION,
        "run_id": "run-1",
        "cluster_id": "c0",
        "signature": "retrieve: empty result",
        "verdict": "rejected",
        "category": "retrieval_miss",
        "root_cause": "cause of c0",
        "suggested_fix": "fix it",
    }


def test_a_lookup_is_filtered_on_the_app_and_the_template_version():
    assert same_app("medas") == {
        "$and": [{"app": {"$eq": "medas"}}, {"v": {"$eq": CHUNK_TEMPLATE_VERSION}}]
    }


def test_near_keeps_the_nearest_k_within_the_distance():
    found = [
        (doc, distance)
        for doc, distance in zip(
            documents("medas", "r", [memory("a"), memory("b"), memory("c")]),
            [0.3, 0.1, 0.2],
            strict=True,
        )
    ]
    assert [m.cluster_id for m in near(found, k=3, max_distance=0.25)] == ["b", "c"]
    assert [m.cluster_id for m in near(found, k=1, max_distance=0.5)] == ["b"]
    assert near([(Document(page_content="x"), 0.9)], k=3, max_distance=0.12) == []


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


def store(engine) -> KnownIssueStore:
    # HashingEmbedder's distances are not bge-small's: no cut, only the filters are tested.
    return KnownIssueStore(engine, HashingEmbedder(EMBEDDING_DIMENSIONS), max_distance=2.0)


@pytest.mark.anyio
async def test_saving_a_run_again_replaces_its_rows(engine):
    assert await store(engine).save("medas", "run-1", [memory("c0")]) == 1
    await store(engine).save("medas", "run-1", [memory("c0")])  # as after a resubmitted review
    async with engine.connect() as conn:
        ids = (await conn.execute(text("SELECT id FROM langchain_pg_embedding"))).scalars()
        assert list(ids) == [f"medas:run-1:c0:v{CHUNK_TEMPLATE_VERSION}"]


@pytest.mark.anyio
async def test_similar_finds_both_verdicts_of_the_same_app_nearest_first(engine):
    timeout = "step: execute_tool search_pubmed\noutcome: error TimeoutError\nlatency: slow"
    empty = "step: retrieval record_chunks\noutcome: ok, hits: none\nlatency: fast"
    await store(engine).save(
        "medas",
        "run-1",
        [memory("c0", "approved", timeout), memory("c1", "rejected", empty)],
    )
    await store(engine).save("other_app", "run-2", [memory("c0", "approved", timeout)])

    found = await store(engine).similar(timeout, "medas", k=5)
    assert [(m.run_id, m.cluster_id, m.verdict) for m in found] == [
        ("run-1", "c0", "approved"),
        ("run-1", "c1", "rejected"),
    ]
    assert found[0].distance < found[1].distance
    assert found[0].root_cause == "cause of c0"
