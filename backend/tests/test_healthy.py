"""runs.healthy: the judge's healthy picks as documents, and stored in Postgres (with
TEST_DATABASE_URL), embedded by an offline stand-in so no model is downloaded."""

import pytest
from sqlalchemy import text

from agent.const import CHUNK_TEMPLATE_VERSION, EMBEDDING_DIMENSIONS
from agent.schemas import HealthyMatch, StepKey
from db.engine import create_engine
from runs.healthy import HealthyStore, compatible, documents, pick_twins
from tests.fakes import HashingEmbedder

PUBMED: StepKey = {
    "step": "execute_tool search_pubmed",
    "operation": "execute_tool",
    "app_version": "2.3.1",
    "schema": "https://opentelemetry.io/schemas/1.37.0",
}
PICK = {"span_id": "s1", **PUBMED, "text": "step: x\noutcome: ok"}
VERDICTS = [
    {"trace_id": "t1", "failed": False, "healthy_spans": [PICK]},
    {"trace_id": "t2", "failed": True, "healthy_spans": []},
    {"trace_id": "t3", "failed": False},  # a verdict from before the picks
    # A pick from before the step key: it cannot be filtered, so it is not stored.
    {"trace_id": "t4", "healthy_spans": [{"span_id": "s", "step": "x", "text": "step: x"}]},
]


def test_each_pick_is_one_document_with_its_filters_and_a_stable_id():
    (doc,) = documents("medas", VERDICTS)
    assert doc.id == f"t1:s1:v{CHUNK_TEMPLATE_VERSION}"
    assert doc.page_content == PICK["text"]
    assert doc.metadata == {
        "app": "medas",
        "trace_id": "t1",
        "span_id": "s1",
        **PUBMED,
        "v": CHUNK_TEMPLATE_VERSION,
    }


def test_compatible_matches_every_key_field_the_app_and_the_template_version():
    conditions = compatible("medas", PUBMED)["$and"]
    assert conditions == [
        {"app": {"$eq": "medas"}},
        *({field: {"$eq": value}} for field, value in PUBMED.items()),
        {"v": {"$eq": CHUNK_TEMPLATE_VERSION}},
    ]


def match(trace_id: str, text: str, distance: float) -> HealthyMatch:
    return HealthyMatch(trace_id=trace_id, span_id="s", text=text, distance=distance)


def test_pick_twins_keeps_the_nearest_k_within_the_distance():
    found = [match("c", "c", 0.3), match("b", "b", 0.2), match("a", "a", 0.1)]
    assert [m.trace_id for m in pick_twins(found, k=3, max_distance=0.25)] == ["a", "b"]
    assert [m.trace_id for m in pick_twins(found, k=1, max_distance=0.5)] == ["a"]


def test_pick_twins_merges_calls_with_the_same_text_and_counts_them():
    found = [match("a", "same", 0.1), match("b", "same", 0.1), match("c", "other", 0.2)]
    twins = pick_twins(found, k=3, max_distance=0.5)
    assert [(m.trace_id, m.calls) for m in twins] == [("a", 2), ("c", 1)]


def test_pick_twins_returns_none_rather_than_far_ones():
    assert pick_twins([match("a", "a", 0.9)], k=3, max_distance=0.12) == []


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


def key(step: str = PUBMED["step"], **fields: str) -> StepKey:
    return {**PUBMED, "step": step, **fields}  # type: ignore[typeddict-item]


def verdict(trace_id: str, key: StepKey, latency: str) -> dict:
    text = f"step: {key['step']}\noutcome: ok\nlatency: {latency}"
    return {"trace_id": trace_id, "healthy_spans": [{"span_id": "s", **key, "text": text}]}


@pytest.mark.anyio
async def test_similar_finds_only_compatible_calls_nearest_first(engine):
    # HashingEmbedder's distances are not bge-small's: no cut, only the filters are tested.
    store = HealthyStore(engine, HashingEmbedder(EMBEDDING_DIMENSIONS), max_distance=2.0)
    await store.save(
        "medas",
        [
            verdict("fast", key(), "fast (<0.5 s)"),
            verdict("slow", key(), "slow (2-5 s)"),
            verdict("other_step", key("execute_tool search_medlineplus"), "slow (2-5 s)"),
            verdict("other_operation", key(operation="chat"), "slow (2-5 s)"),
            verdict("other_version", key(app_version="2.4.0"), "slow (2-5 s)"),
            verdict("other_schema", key(schema="https://example.org/s/2"), "slow (2-5 s)"),
        ],
    )
    await store.save("other_app", [verdict("other_app", key(), "slow (2-5 s)")])

    query = f"step: {PUBMED['step']}\noutcome: error TimeoutError\nlatency: slow (2-5 s)"
    found = await store.similar(query, "medas", PUBMED, k=5)
    assert [match.trace_id for match in found] == ["slow", "fast"]
    assert found[0].distance < found[1].distance and found[0].text.endswith("slow (2-5 s)")


@pytest.mark.anyio
async def test_similar_finds_nothing_for_a_step_with_no_healthy_calls(engine):
    store = HealthyStore(engine, HashingEmbedder(EMBEDDING_DIMENSIONS))
    await store.save("medas", VERDICTS)
    assert await store.similar("step: x", "medas", key("execute_tool never_seen"), 3) == []
