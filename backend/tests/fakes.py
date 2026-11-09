"""Test doubles shared by the graph and API tests."""

import numpy as np
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sklearn.feature_extraction.text import HashingVectorizer

from agent.context import TraceContext, TraceSearch
from trace_store.models import FailedTraceQuery, TraceSummary


class HashingEmbedder:
    """Offline stand-in for the real embedder: character n-gram hashing, fully deterministic."""

    def __init__(self) -> None:
        self._vectorizer = HashingVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), n_features=2**12, alternate_sign=False
        )

    def embed(self, texts: list[str]) -> np.ndarray:
        return self._vectorizer.transform(texts).toarray()


class FakeTraces:
    def __init__(self, found: list[TraceSummary] | None = None) -> None:
        self.found = found or []
        self.queries: list[FailedTraceQuery] = []

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        self.queries.append(query)
        return self.found


def fake_model() -> BaseChatModel:
    """Offline stand-in for the diagnoser's chat model."""
    return FakeListChatModel(responses=[])


def fake_context(traces: TraceSearch) -> TraceContext:
    """A run context whose embedder and chat model are offline stand-ins."""
    return TraceContext(traces, HashingEmbedder(), fake_model())


def summary(trace_id: str, **overrides) -> TraceSummary:
    return TraceSummary.model_validate(
        {
            "trace_id": trace_id,
            "app": "medas",
            "start_time": "2026-11-05T10:00:00Z",
            "duration_ms": 120.0,
            "status": "error",
            "signature": "retrieve: empty result",
            **overrides,
        }
    )
