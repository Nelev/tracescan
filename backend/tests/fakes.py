"""Test doubles shared by the graph and API tests."""

import re
from collections.abc import Callable

import numpy as np
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel, GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from sklearn.feature_extraction.text import HashingVectorizer

from agent.context import TraceAccess, TraceContext
from agent.schemas import Diagnosis, Evidence
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


class ScriptedModel(FakeListChatModel):
    """A chat model that replies with the next of `responses` (they repeat), recording in `seen`
    what it was asked."""

    seen: list = []

    def _call(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._call(messages, *args, **kwargs)


def scripted(*replies: str) -> ScriptedModel:
    return ScriptedModel(responses=list(replies), seen=[])


# A UI spec as the small model would write it, for the stream and the UI spec tests.
SPEC = {"root": "page", "elements": {"page": {"type": "Stack", "props": {}, "children": []}}}


def fake_model() -> BaseChatModel:
    """Offline stand-in for the diagnoser's chat model; it is never called."""
    return FakeListChatModel(responses=[])


class FakeApiError(Exception):
    """What the OpenRouter SDK raises for an HTTP error: a status code and a message."""

    def __init__(self, status_code: int, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class FakeDiagnoserModel(GenericFakeChatModel):
    """Answers `with_structured_output(Diagnosis)` with `answer(messages)`, recording the calls.

    `answer` returns a Diagnosis, or raises to make a failing call. Every answer reports 150 tokens
    and a cost of $0.001, as the real model does.
    """

    seen: list[list[BaseMessage]] = Field(default_factory=list)
    answer: Callable[[list[BaseMessage]], Diagnosis]

    def with_structured_output(self, schema, *, method=None, **kwargs):
        # Accepts `method` like ChatOpenRouter does, but the fake only ever answers with a tool call.
        return super().with_structured_output(schema, **kwargs)

    def bind_tools(self, tools, **kwargs):
        return self  # the reply below already is the tool call that structured output parses

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        args = self.answer(messages).model_dump(mode="json")
        call = {"name": "Diagnosis", "args": args, "id": "call_1"}
        message = AIMessage(
            "",
            tool_calls=[call],
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            response_metadata={"cost": 0.001},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


# The first span of a tree in the prompt, as the prompt prints it (span_id comes first).
_SPAN_IN_PROMPT = re.compile(r'"span_id":"([^"]+)","trace_id":"([^"]+)"')


def first_span_shown(messages: list[BaseMessage]) -> Evidence:
    """What a careful diagnoser cites: the first span of the first trace in the prompt."""
    span_id, trace_id = _SPAN_IN_PROMPT.search(str(messages[1].content)).groups()  # type: ignore[union-attr]
    return Evidence(trace_id=trace_id, span_id=span_id, note="retrieve returned nothing")


def fake_diagnoser(diagnosis: Diagnosis) -> FakeDiagnoserModel:
    """A well-behaved model: every cluster gets `diagnosis`, citing a span it was really shown."""
    return FakeDiagnoserModel(
        messages=iter(()),
        answer=lambda messages: diagnosis.model_copy(
            update={"evidence": [first_span_shown(messages)]}
        ),
    )


def scripted_diagnoser(*answers: Diagnosis | Exception) -> FakeDiagnoserModel:
    """Gives each call the next answer, verbatim (citations included), then repeats the last.

    An Exception in the script is raised instead of answered.
    """
    remaining = list(answers)

    def answer(_: list[BaseMessage]) -> Diagnosis:
        item = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(item, Exception):
            raise item
        return item

    return FakeDiagnoserModel(messages=iter(()), answer=answer)


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
