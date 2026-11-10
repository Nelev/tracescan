"""Seed the `spans` table with synthetic Medas traces, in the shape real ones will have.

Run from backend/:  uv run --env-file .env python -m scripts.seed_traces [--end 2026-11-10T12:00:00Z]

The spans are made with the OpenTelemetry SDK, encoded as an OTLP export and decoded by the
collector's own `decode`, so they reach the table the way a posted export does. Names and
attributes follow the gen_ai semantic conventions (still in development upstream): a root
`invoke_agent` span, `chat` spans for model calls, `execute_tool` spans, and a `retrieval` span
under the record search. No prompt, answer or passage text: every value is made up here.

One run is a day of traffic that ends at `--end` (now, by default): four kinds of failure that
repeat, one that happens once, and healthy requests. Ids and values are drawn from `end`, so
the same `end` twice stores nothing new and another `end` adds another day.
"""

import argparse
import asyncio
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from random import Random
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.trace import SpanKind, Status, StatusCode
from sqlalchemy.exc import SQLAlchemyError

from api.traces import decode, store_spans
from db.engine import create_engine

APP = "medas"
MODEL = "openai/gpt-4.1-mini"
DAY = timedelta(hours=24)
GAP_NS = 5_000_000  # between a span and the next one under the same parent

Error = tuple[str, str]  # exception type, message


@dataclass(frozen=True)
class Step:
    """One span to make. A step with children lasts as long as they do; a leaf lasts `ms`."""

    name: str
    kind: SpanKind
    attributes: Mapping[str, Any]
    ms: int = 0
    error: Error | None = None
    children: tuple["Step", ...] = ()


class SeededIds(IdGenerator):
    def __init__(self, rng: Random) -> None:
        self._rng = rng

    def generate_span_id(self) -> int:
        return self._rng.getrandbits(64) or 1

    def generate_trace_id(self) -> int:
        return self._rng.getrandbits(128) or 1


def chat(rng: Random, error: Error | None = None) -> Step:
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "openai",
        "gen_ai.request.model": MODEL,
    }
    if error is None:  # a call that failed reports no usage
        attributes["gen_ai.usage.input_tokens"] = rng.randint(900, 4000)
        attributes["gen_ai.usage.output_tokens"] = rng.randint(40, 400)
    return Step(f"chat {MODEL}", SpanKind.CLIENT, attributes, rng.randint(600, 2500), error)


def tool(rng: Random, name: str, *children: Step, ms: int = 0, error: Error | None = None) -> Step:
    attributes = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": name,
        "gen_ai.tool.type": "function",
        "gen_ai.tool.call.id": f"call_{rng.getrandbits(48):012x}",
    }
    return Step(f"execute_tool {name}", SpanKind.INTERNAL, attributes, ms, error, children)


def retrieval(rng: Random, error: Error | None = None) -> Step:
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": "retrieval",
        "gen_ai.data_source.id": "record_chunks",
    }
    if error is None:
        attributes["medas.retrieval.hits"] = 5
    return Step("retrieval record_chunks", SpanKind.CLIENT, attributes, rng.randint(80, 300), error)


def request(rng: Random, *children: Step, error: Error | None = None) -> Step:
    attributes = {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.agent.name": APP,
        "gen_ai.conversation.id": f"conv_{rng.getrandbits(48):012x}",
    }
    return Step(f"invoke_agent {APP}", SpanKind.SERVER, attributes, 0, error, children)


def record_search(rng: Random) -> Step:
    return tool(rng, "search_patient_record", retrieval(rng))


# The request fails as a whole when the model cannot be reached: Medas raises AgentUnavailable.
UNAVAILABLE: Error = ("schema.AgentUnavailable", "the agent could not answer")


def healthy(rng: Random) -> Step:
    lookup = rng.choice(
        [record_search(rng), tool(rng, "search_medlineplus", ms=rng.randint(200, 900))]
    )
    return request(rng, chat(rng), lookup, chat(rng))


def source_timeout(rng: Random) -> Step:
    """A public source does not answer. The tool says so to the model, so the request goes on."""
    seconds = rng.uniform(10.0, 10.4)
    error = ("httpx.ReadTimeout", f"search_pubmed timed out after {seconds:.1f}s")
    lookup = tool(rng, "search_pubmed", ms=int(seconds * 1000), error=error)
    return request(rng, chat(rng), lookup, chat(rng))


def tool_arguments(rng: Random) -> Step:
    """The model calls a tool with arguments its schema refuses."""
    error = (
        "pydantic_core._pydantic_core.ValidationError",
        "1 validation error for export_conversation: format: Input should be a valid string",
    )
    return request(rng, chat(rng), tool(rng, "export_conversation", ms=2, error=error), chat(rng))


def model_unavailable(rng: Random) -> Step:
    """The provider answers the first model call with a server error."""
    error = ("openai.InternalServerError", f"Error code: {rng.choice([502, 503])}")
    return request(rng, chat(rng, error), error=UNAVAILABLE)


def context_overflow(rng: Random) -> Step:
    """After a record search, the second model call is over the model's context length."""
    asked = rng.randint(1_048_000, 1_090_000)
    error = (
        "openai.BadRequestError",
        f"Error code: 400 - maximum context length is 1047576 tokens, requested {asked}",
    )
    return request(rng, chat(rng), record_search(rng), chat(rng, error), error=UNAVAILABLE)


def store_down(rng: Random) -> Step:
    """The record search cannot reach its database. Happens once, so it should not cluster."""
    error = ("sqlalchemy.exc.OperationalError", "connection to the record store was refused")
    search = tool(rng, "search_patient_record", retrieval(rng, error), error=error)
    return request(rng, chat(rng), search, error=error)


# How many traces of each kind one run makes.
COUNTS: dict[Callable[[Random], Step], int] = {
    healthy: 8,
    source_timeout: 6,
    tool_arguments: 5,
    model_unavailable: 5,
    context_overflow: 5,
    store_down: 1,
}


def _emit(tracer: trace.Tracer, step: Step, parent: trace.Span | None, start_ns: int) -> int:
    """Make the span of `step` and of everything under it; returns when it ended."""
    context = trace.set_span_in_context(parent) if parent is not None else None
    span = tracer.start_span(
        step.name,
        context=context,
        kind=step.kind,
        attributes=step.attributes,
        start_time=start_ns,
    )
    end_ns = start_ns + step.ms * 1_000_000
    for child in step.children:
        end_ns = _emit(tracer, child, span, end_ns + GAP_NS)
    if step.children:
        end_ns += GAP_NS
    if step.error is not None:
        kind, message = step.error
        span.set_attribute("error.type", kind)
        span.add_event(
            "exception",
            {"exception.type": kind, "exception.message": message},
            timestamp=end_ns,
        )
        span.set_status(Status(StatusCode.ERROR, message))
    span.end(end_time=end_ns)
    return end_ns


def _day(end: datetime) -> tuple[Sequence[ReadableSpan], dict[str, str]]:
    """The spans of the day that ends at `end`, and the kind of each of its traces."""
    rng = Random(int(end.timestamp()))
    finished = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource({"service.name": APP}), id_generator=SeededIds(rng))
    provider.add_span_processor(SimpleSpanProcessor(finished))
    tracer = provider.get_tracer("scripts.seed_traces")

    makers = [make for make, count in COUNTS.items() for _ in range(count)]
    rng.shuffle(makers)
    # One request per slot, started at the slot's start: each is over well before `end`.
    slot = DAY / len(makers)
    kinds = {}
    for i, make in enumerate(makers):
        start = end - DAY + slot * i
        _emit(tracer, make(rng), None, int(start.timestamp() * 1e9))
        context = finished.get_finished_spans()[
            -1
        ].context  # any span just made: all are of this trace
        assert context is not None  # a span the SDK made always has one
        kinds[format(context.trace_id, "032x")] = make.__name__
    return finished.get_finished_spans(), kinds


def export(end: datetime) -> bytes:
    """The day of traffic that ends at `end`, as one OTLP trace export."""
    return encode_spans(_day(end)[0]).SerializeToString()


def kinds(end: datetime) -> dict[str, str]:
    """What each trace of that day is: trace id to the name of its maker in COUNTS.

    The answer key of the eval (eval/ground_truth.py). It is worked out again from `end`
    and never stored, so nothing the diagnoser can read says what a trace is.
    """
    return _day(end)[1]


async def seed(database_url: str, rows: list[dict[str, Any]]) -> int:
    """Store the rows as the collector does. Returns how many were new."""
    engine = create_engine(database_url)
    try:
        return await store_spans(engine, rows)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--end",
        type=datetime.fromisoformat,
        default=datetime.now(UTC),
        help="when the day of traffic ends, as an ISO date and time with an offset (default: now)",
    )
    end = parser.parse_args().end
    if end.tzinfo is None:
        parser.error("--end needs an offset, for example 2026-11-10T12:00:00Z")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("set DATABASE_URL (the application's role: it writes to spans)")

    rows = decode(export(end))
    try:
        new = asyncio.run(seed(database_url, rows))
    except SQLAlchemyError as exc:
        # By type only: the error's own text repeats every row.
        raise SystemExit(
            f"could not store the spans ({type(exc).__name__}): "
            "is the database up and migrated (alembic upgrade head)?"
        ) from None
    traces = len({row["trace_id"] for row in rows})
    print(f"{traces} traces, {len(rows)} spans ending {end.isoformat()}: {new} spans new")


if __name__ == "__main__":
    main()
