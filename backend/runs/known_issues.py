"""The known-issues memory: diagnoses a reviewer decided on, embedded, so a later run's diagnoser
sees what was confirmed, and what was rejected, for failures like the one in front of it.

langchain-postgres's PGVector on the application's engine, in the application's database, beside
the healthy spans: one collection, `known_issues`, in the same two tables (migration 0006 brought
the `vector` extension; PGVector creates the tables on first use).

What is embedded is what a later run searches with: the failing span's step_text (agent.chunks:
names, error types and bucketed numbers, no span content). A new cluster knows its symptom but not
its cause, so the cause, the fix and the verdict go into metadata and come back with the match.
The id is the app, the run, the cluster and the chunk template version, so an apply that runs
again (a resubmitted review) replaces its rows instead of adding to them.

Written only by apply_actions, after a person's decision: approved diagnoses as confirmed causes,
rejected ones as warnings. A rejected one must never be used to match or suppress an issue.
The metadata holds the diagnoser's prose (possibly clinical); it stays in this database.
"""

from collections.abc import Sequence

from langchain_core.documents import Document
from langchain_postgres import PGVector
from sqlalchemy.ext.asyncio import AsyncEngine

from agent.const import CHUNK_TEMPLATE_VERSION, EMBEDDING_DIMENSIONS, MAX_ISSUE_DISTANCE
from agent.embeddings import Embedder
from agent.schemas import IssueMemory, KnownIssue
from runs.healthy import LocalEmbeddings

COLLECTION = "known_issues"
# Candidates fetched per match asked for, so dropping far ones still leaves enough to choose from.
OVERFETCH = 2


def documents(app: str, run_id: str, memories: Sequence[IssueMemory]) -> list[Document]:
    """One document per memory: its failing step embedded, the rest as metadata. Pure."""
    return [
        Document(
            id=f"{app}:{run_id}:{memory['cluster_id']}:v{CHUNK_TEMPLATE_VERSION}",
            page_content=memory["failing_step"],
            metadata={
                "app": app,
                "v": CHUNK_TEMPLATE_VERSION,
                "run_id": run_id,
                **{key: value for key, value in memory.items() if key != "failing_step"},
            },
        )
        for memory in memories
    ]


def same_app(app: str) -> dict:
    """The metadata filter of a lookup: the same app and chunk template version. Pure."""
    return {"$and": [{"app": {"$eq": app}}, {"v": {"$eq": CHUNK_TEMPLATE_VERSION}}]}


def near(
    found: Sequence[tuple[Document, float]], k: int, max_distance: float = MAX_ISSUE_DISTANCE
) -> list[KnownIssue]:
    """At most `k` of the found documents, nearest first, none farther than `max_distance`. Pure."""
    return [
        KnownIssue(
            verdict=doc.metadata["verdict"],
            category=doc.metadata["category"],
            root_cause=doc.metadata["root_cause"],
            suggested_fix=doc.metadata["suggested_fix"],
            signature=doc.metadata["signature"],
            run_id=doc.metadata["run_id"],
            cluster_id=doc.metadata["cluster_id"],
            distance=distance,
        )
        for doc, distance in sorted(found, key=lambda pair: pair[1])
        if distance <= max_distance
    ][:k]


class KnownIssueStore:
    def __init__(
        self, engine: AsyncEngine, embedder: Embedder, max_distance: float = MAX_ISSUE_DISTANCE
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

    async def save(self, app: str, run_id: str, memories: Sequence[IssueMemory]) -> int:
        """Embed and store the memories of one reviewed run; returns how many."""
        docs = documents(app, run_id, memories)
        if docs:
            await self._vectors.aadd_documents(docs)
        return len(docs)

    async def similar(self, text: str, app: str, k: int) -> list[KnownIssue]:
        """Up to `k` decided diagnoses of `app` whose failing step is near `text`, nearest first:
        fewer, or none, when not enough are near enough."""
        found = await self._vectors.asimilarity_search_with_score(
            text, k=k * OVERFETCH, filter=same_app(app)
        )
        return near(found, k, self._max_distance)
