"""The healthy-span store: the judge's healthy picks, embedded, so a failed step can later be
compared with the same step working.

langchain-postgres's PGVector on the application's engine, in the application's database: one
collection, `healthy_spans`, in the two tables PGVector creates on first use (the `vector`
extension comes from migration 0006). A document is a pick's `step_text` (agent.chunks): names,
error types and bucketed numbers only, never span content. Its id is the trace, the span and the
chunk template version, so saving a window again replaces rows instead of adding them.

A failed step is compared only with healthy calls it is compatible with: the same app, step,
operation, app version, telemetry schema and chunk template version, all hard filters applied in
the same query as the vector search. The nearest few within MAX_TWIN_DISTANCE come back, with
identical texts merged, so the diagnoser may see fewer than it asked for, or none.

Written for every run that ends or pauses at the review, without a person's approval: the one
write outside apply_actions. It holds no clinical text and never leaves the database.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Protocol

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector
from sqlalchemy.ext.asyncio import AsyncEngine

from agent.const import CHUNK_TEMPLATE_VERSION, EMBEDDING_DIMENSIONS, MAX_TWIN_DISTANCE
from agent.embeddings import Embedder
from agent.schemas import HealthyMatch, StepKey

COLLECTION = "healthy_spans"
# Candidates fetched per twin asked for, so merging identical texts still leaves enough.
OVERFETCH = 4


class LocalEmbeddings(Embeddings):
    """The local embedder as LangChain's Embeddings, so trace text never leaves the machine."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)  # CPU-bound

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]


class HealthySpans(Protocol):
    async def save(self, app: str, verdicts: Sequence[Mapping]) -> int: ...


def documents(app: str, verdicts: Sequence[Mapping]) -> list[Document]:
    """One document per healthy pick of the verdicts. Pure."""
    return [
        Document(
            id=f"{verdict['trace_id']}:{pick['span_id']}:v{CHUNK_TEMPLATE_VERSION}",
            page_content=pick["text"],
            metadata={
                "app": app,
                "trace_id": verdict["trace_id"],
                "span_id": pick["span_id"],
                **{field: pick[field] for field in StepKey.__annotations__},
                "v": CHUNK_TEMPLATE_VERSION,
            },
        )
        for verdict in verdicts
        for pick in verdict.get("healthy_spans", [])
        # A pick saved before the step key existed cannot be filtered: left out.
        if StepKey.__annotations__.keys() <= pick.keys()
    ]


def compatible(app: str, key: StepKey) -> dict:
    """The metadata filter a healthy call must pass to be compared with a step of `key`. Pure."""
    fields = {"app": app, **key, "v": CHUNK_TEMPLATE_VERSION}
    return {"$and": [{field: {"$eq": value}} for field, value in fields.items()]}


def pick_twins(
    found: Sequence[HealthyMatch], k: int, max_distance: float = MAX_TWIN_DISTANCE
) -> list[HealthyMatch]:
    """At most `k` of the matches, nearest first: none farther than `max_distance`, and one per
    distinct text, counting the calls that share it. Fewer, or none, when no more qualify. Pure."""
    kept: dict[str, HealthyMatch] = {}
    for match in sorted(found, key=lambda m: m.distance):
        if match.distance > max_distance:
            break
        if (same := kept.get(match.text)) is not None:
            kept[match.text] = replace(same, calls=same.calls + match.calls)
        elif len(kept) < k:
            kept[match.text] = match
    return list(kept.values())


class HealthyStore:
    def __init__(
        self, engine: AsyncEngine, embedder: Embedder, max_distance: float = MAX_TWIN_DISTANCE
    ) -> None:
        self._max_distance = max_distance
        self._vectors = PGVector(
            embeddings=LocalEmbeddings(embedder),
            collection_name=COLLECTION,
            connection=engine,
            embedding_length=EMBEDDING_DIMENSIONS,
            use_jsonb=True,
            create_extension=False,  # migration 0006: the app's role need not own extensions
            async_mode=True,
        )

    async def save(self, app: str, verdicts: Sequence[Mapping]) -> int:
        """Embed and store every healthy pick of the verdicts; returns how many."""
        docs = documents(app, verdicts)
        if docs:
            await self._vectors.aadd_documents(docs)
        return len(docs)

    async def similar(self, text: str, app: str, key: StepKey, k: int) -> list[HealthyMatch]:
        """Up to `k` stored healthy calls compatible with a step of `key` in `app`, nearest to
        `text` first (pick_twins): fewer, or none, when not enough are near enough."""
        found = await self._vectors.asimilarity_search_with_score(
            text, k=k * OVERFETCH, filter=compatible(app, key)
        )
        return pick_twins(
            [
                HealthyMatch(
                    trace_id=doc.metadata["trace_id"],
                    span_id=doc.metadata["span_id"],
                    text=doc.page_content,
                    distance=distance,
                )
                for doc, distance in found
            ],
            k,
            self._max_distance,
        )
