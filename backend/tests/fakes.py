"""Test doubles shared by the graph and API tests."""

import re
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel, GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import HashingVectorizer

from agent.context import TraceAccess, TraceContext
from agent.schemas import Decision, Diagnosis, Evidence
from runs.store import (
    CLAIMABLE,
    ENDED,
    NotClaimable,
    ReviewRecord,
    RunCounts,
    RunRecord,
    StoredStatus,
)
from trace_store.models import FailedTraceQuery, SpanNode, TraceSummary
from trace_store.reader import build_tree


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


def files_under(path: Path) -> list[str]:
    """Every file under `path`, relative to it and sorted: what a dry run wrote."""
    return sorted(str(f.relative_to(path)) for f in path.rglob("*") if f.is_file())


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


class InMemoryRunStore:
    """The run store without a database: what runs.store.RunStore promises, in two dicts."""

    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}
        self.decided: dict[str, list[ReviewRecord]] = {}
        self.held: set[str] = set()  # runs a review is being applied to

    async def create_run(
        self,
        run_id: str,
        target_app: str,
        since: datetime | None,
        until: datetime | None,
        status: StoredStatus,
        user: str | None,
    ) -> None:
        if run_id in self.runs:
            return
        self.runs[run_id] = RunRecord(
            run_id=run_id,
            target_app=target_app,
            since=since,
            until=until,
            status=status,
            started_by=user,
            created_at=datetime.now(UTC),
            ended_at=None,
            failed_traces=0,
            clusters=0,
            proposals=0,
        )

    async def set_status(
        self, run_id: str, status: StoredStatus, counts: RunCounts | None = None
    ) -> None:
        if run_id not in self.runs:
            return
        changes: dict = {"status": status}
        if status in ENDED:
            changes["ended_at"] = datetime.now(UTC)
        if counts is not None:
            changes |= asdict(counts)
        self.runs[run_id] = self.runs[run_id].model_copy(update=changes)

    @asynccontextmanager
    async def reviewing(self, run_id: str, decisions: Mapping[str, Decision], reviewer: str):
        # No await before the run is held, so two reviews cannot both get in.
        run = self.runs.get(run_id)
        if run is None or run.status not in CLAIMABLE or run_id in self.held:
            raise NotClaimable
        self.held.add(run_id)
        self.decided[run_id] = [
            ReviewRecord(
                cluster_id=cluster_id,
                decision=decision,
                reviewer=reviewer,
                decided_at=datetime.now(UTC),
            )
            for cluster_id, decision in sorted(decisions.items())
        ]

        async def finish(status: StoredStatus, counts: RunCounts) -> None:
            await self.set_status(run_id, status, counts)

        try:
            yield finish
        except BaseException:  # what a rolled-back transaction leaves: nothing
            self.runs[run_id] = run
            del self.decided[run_id]
            raise
        finally:
            self.held.discard(run_id)

    async def get_run(self, run_id: str) -> RunRecord | None:
        return self.runs.get(run_id)

    async def list_runs(self, limit: int) -> list[RunRecord]:
        newest_first = sorted(self.runs.values(), key=lambda r: r.created_at, reverse=True)
        return newest_first[:limit]

    async def reviews(self, run_id: str) -> list[ReviewRecord]:
        return self.decided.get(run_id, [])


FIXTURE = Path(__file__).parent / "fixtures" / "medas_traces.json"


def _fixture_failed(summary: TraceSummary, max_score: float) -> bool:
    """Its lowest score is low. A summary with no score counts a status of error as 0."""
    score = summary.min_score
    if score is None:
        score = 0.0 if summary.status == "error" else 1.0
    return score <= max_score


class _FixtureTrace(BaseModel):
    summary: TraceSummary
    spans: list[SpanNode]


class _FixtureFile(BaseModel):
    traces: list[_FixtureTrace]


class FixtureTraceReader:
    """A TraceReader over three hand-written traces (tests/fixtures/medas_traces.json), for the
    trace server's own tests: its tools, its sanitizing and its guard need no database."""

    def __init__(self, path: Path = FIXTURE) -> None:
        self._summaries: dict[str, TraceSummary] = {}
        self._trees: dict[str, SpanNode] = {}
        self._spans: dict[str, dict[str, SpanNode]] = {}
        for trace in _FixtureFile.model_validate_json(path.read_bytes()).traces:
            trace_id = trace.summary.trace_id
            tree = build_tree(trace.spans)  # fails at load time on a broken fixture
            if tree.trace_id != trace_id:
                raise ValueError(f"spans do not belong to trace {trace_id}")
            self._summaries[trace_id] = trace.summary
            self._trees[trace_id] = tree
            self._spans[trace_id] = {s.span_id: s for s in trace.spans}

    async def search_failed_traces(self, query: FailedTraceQuery) -> list[TraceSummary]:
        matches = [
            s
            for s in self._summaries.values()
            if s.app == query.app
            and (query.since is None or s.start_time >= query.since)
            and (query.until is None or s.start_time < query.until)
            and _fixture_failed(s, query.max_score)
        ]
        matches.sort(key=lambda s: s.start_time, reverse=True)
        return matches[: query.limit]

    async def get_trace_tree(self, trace_id: str) -> SpanNode | None:
        return self._trees.get(trace_id)

    async def get_span(self, trace_id: str, span_id: str) -> SpanNode | None:
        span = self._spans.get(trace_id, {}).get(span_id)
        return span.model_copy(update={"children": []}) if span else None
