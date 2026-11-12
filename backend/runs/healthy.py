"""The healthy-span store: the judge's healthy picks, embedded, so a failed step can later be
compared with the same step working.

langchain-postgres's PGVector on the application's engine, in the application's database: one
collection, `healthy_spans`, in the two tables PGVector creates on first use (the `vector`
extension comes from migration 0006). A document is a pick's `step_text` (agent.chunks): names,
error types and bucketed numbers only, never span content. Its id is the trace, the span and the
chunk template version, so saving a window again replaces rows instead of adding them.

Written for every run that ends or pauses at the review, without a person's approval: the one
write outside apply_actions. It holds no clinical text and never leaves the database.
"""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Protocol

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector
from sqlalchemy.ext.asyncio import AsyncEngine

from agent.const import CHUNK_TEMPLATE_VERSION, EMBEDDING_DIMENSIONS
from agent.embeddings import Embedder
from runs.schemas import HealthyMatch

COLLECTION = "healthy_spans"


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
                "step": pick["step"],
                "v": CHUNK_TEMPLATE_VERSION,
            },
        )
        for verdict in verdicts
        for pick in verdict.get("healthy_spans", [])
    ]


class HealthyStore:
    def __init__(self, engine: AsyncEngine, embedder: Embedder) -> None:
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

    async def similar(self, text: str, step: str, app: str, k: int = 3) -> list[HealthyMatch]:
        """The `k` stored healthy calls of `step` in `app` nearest to `text`, nearest first.

        Only rows of the current chunk template: a text of another version is not comparable.
        No threshold yet: bge-small's scores bunch together, so one is tuned on the eval later.
        """
        found = await self._vectors.asimilarity_search_with_score(
            text,
            k=k,
            filter={
                "$and": [
                    {"app": {"$eq": app}},
                    {"step": {"$eq": step}},
                    {"v": {"$eq": CHUNK_TEMPLATE_VERSION}},
                ]
            },
        )
        return [
            HealthyMatch(
                trace_id=doc.metadata["trace_id"],
                span_id=doc.metadata["span_id"],
                text=doc.page_content,
                distance=distance,
            )
            for doc, distance in found
        ]
