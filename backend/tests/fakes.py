"""Test doubles shared by the graph and API tests."""

from itertools import cycle

import numpy as np
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel, GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import Field
from sklearn.feature_extraction.text import HashingVectorizer

from agent.context import TraceAccess, TraceContext
from agent.schemas import Diagnosis
from trace_store.models import FailedTraceQuery, SpanNode, TraceSummary


class HashingEmbedder:
    """Offline stand-in for the real embedder: character n-gram hashing, fully deterministic."""

    def __init__(self) -> None:
        self._vectorizer = HashingVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), n_features=2**12, alternate_sign=False
        )

    def embed(self, texts: list[str]) -> np.ndarray:
        return self._vectorizer.transform(texts).toarray()


class FakeTraces:
    def __init__(
        self, found: list[TraceSummary] | None = None, trees: dict[str, SpanNode] | None = None
    ) -> None:
        self.found = found or []
        self.trees = trees or {}
        self.queries: list[FailedTraceQuery] = []

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        self.queries.append(query)
        return self.found

    async def get_trace_tree(self, trace_id: str) -> SpanNode:
        return self.trees[trace_id]


def fake_model() -> BaseChatModel:
    """Offline stand-in for the diagnoser's chat model; it is never called."""
    return FakeListChatModel(responses=[])


class FakeDiagnoserModel(GenericFakeChatModel):
    """Answers `with_structured_output(Diagnosis)` with a fixed diagnosis, recording what it saw."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self  # the reply below already is the tool call that structured output parses

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


def fake_diagnoser(diagnosis: Diagnosis) -> FakeDiagnoserModel:
    """A model that gives the same answer however many clusters ask."""
    call = {"name": "Diagnosis", "args": diagnosis.model_dump(mode="json"), "id": "call_1"}
    return FakeDiagnoserModel(messages=cycle([AIMessage(content="", tool_calls=[call])]))


def fake_context(traces: TraceAccess, model: BaseChatModel | None = None) -> TraceContext:
    """A run context whose embedder is an offline stand-in and whose chat model is a fake."""
    return TraceContext(traces, HashingEmbedder(), model or fake_model())


def span_tree(trace_id: str, **overrides) -> SpanNode:
    """A one-span trace: a failing retrieve step."""
    return SpanNode.model_validate(
        {
            "span_id": f"{trace_id}_root",
            "trace_id": trace_id,
            "name": "retrieve",
            "start_time": "2026-11-05T10:00:00Z",
            "end_time": "2026-11-05T10:00:01Z",
            "status": "error",
            "status_message": "empty result",
            **overrides,
        }
    )


# What a model might answer, with a cluster id of its own invention.
DIAGNOSIS = Diagnosis.model_validate(
    {
        "cluster_id": "made-up",
        "category": "retrieval_miss",
        "root_cause": "The retriever's filter excludes the drug-interaction category.",
        "suggested_fix": "Include the category in the filter.",
        "confidence": 0.7,
        "evidence": [{"trace_id": "t1", "span_id": "s1", "note": "retrieve returned nothing"}],
    }
)


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
