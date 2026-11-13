"""The trace collector: OTLP over HTTP in, rows in `spans` out.

    POST /v1/traces   Authorization: Bearer <app token>   Content-Type: application/x-protobuf

Binary protobuf, uncompressed: the OTel exporters' default. The token says which app is sending
(`COLLECTOR_TOKEN_<APP>`, one per allowed app, read once at startup), and only that app's spans are stored, so one app's
token cannot write another's traces. Medas's exporter sends it through
`OTEL_EXPORTER_OTLP_TRACES_HEADERS=Authorization=Bearer%20<token>`.

An export is at most MAX_EXPORT_BYTES and MAX_EXPORT_SPANS (413 past either). On the way in, NUL
characters are stripped and non-finite numbers become null (Postgres refuses both, and with them
the whole batch), names and status messages are cut, and spans that start in the future are
dropped. Nothing here logs a span.
"""

import hmac
import logging
import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span as OtlpSpan
from opentelemetry.proto.trace.v1.trace_pb2 import Status
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from auth import bearer_scheme, unauthorized
from db.models import Span
from trace_store.const import (
    ALLOWED_APPS,
    APP_VERSION_MAX,
    COLLECTOR_TOKEN_MIN,
    MAX_CLOCK_SKEW_S,
    MAX_EXPORT_BYTES,
    MAX_EXPORT_SPANS,
    SCHEMA_URL_MAX,
    SPAN_NAME_MAX,
    STATUS_MESSAGE_MAX,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")

PROTOBUF = "application/x-protobuf"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# OTLP's enum numbers as words: SPAN_KIND_SERVER is "server", STATUS_CODE_ERROR is "error".
KINDS = {v: name.removeprefix("SPAN_KIND_").lower() for name, v in OtlpSpan.SpanKind.items()}
STATUSES = {v: name.removeprefix("STATUS_CODE_").lower() for name, v in Status.StatusCode.items()}


def token_variable(app: str) -> str:
    """The environment variable holding an app's collector token: COLLECTOR_TOKEN_MEDAS."""
    return f"COLLECTOR_TOKEN_{app.upper()}"


@dataclass(frozen=True)
class CollectorTokens:
    """Which app each collector token belongs to, from the environment."""

    by_app: Mapping[str, str]

    @classmethod
    def from_env(cls) -> "CollectorTokens":
        """One token per allowed app, each in its own variable (`token_variable`). Raises
        `KeyError` for a missing one and `ValueError` for one that is too short or shared."""
        tokens = {app: os.environ[token_variable(app)] for app in ALLOWED_APPS}
        if any(len(token) < COLLECTOR_TOKEN_MIN for token in tokens.values()):
            raise ValueError(
                f"each collector token needs at least {COLLECTOR_TOKEN_MIN} characters"
            )
        if len(set(tokens.values())) != len(tokens):
            raise ValueError("each app needs its own collector token")
        return cls(tokens)

    def app_of(self, token: str) -> str | None:
        """The app this token belongs to, or None. Compares against every token, in constant
        time each, so the answer's timing says nothing about which one nearly matched."""
        found = None
        for app, expected in self.by_app.items():
            if hmac.compare_digest(token.encode(), expected.encode()):
                found = app
        return found


def sending_app(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    """The app whose token the request carries; 401 without one. Runs before the body is read."""
    tokens: CollectorTokens = request.app.state.collector_tokens
    app = None if credentials is None else tokens.app_of(credentials.credentials)
    if app is None:
        raise unauthorized("missing or unknown collector token")
    return app


class ExportTooLarge(Exception):
    """An export with more than MAX_EXPORT_SPANS spans."""


def _text(value: str, width: int | None = None) -> str:
    """Text as stored: without NUL characters, which Postgres refuses, and cut to `width`."""
    clean = value.replace("\x00", "")
    return clean if width is None else clean[:width]


def _value(value: AnyValue) -> Any:
    """An attribute value as a plain JSON value; scalars and arrays only."""
    match value.WhichOneof("value"):
        case "string_value":
            return _text(value.string_value)
        case "bool_value":
            return value.bool_value
        case "int_value":
            return value.int_value
        case "double_value":
            # NaN and infinities are not JSON: Postgres would refuse the batch.
            return value.double_value if math.isfinite(value.double_value) else None
        case "array_value":
            return [_value(item) for item in value.array_value.values]
        case _:
            return None


def _attributes(pairs: Iterable[KeyValue]) -> dict[str, Any]:
    return {_text(pair.key): _value(pair.value) for pair in pairs}


def _time(unix_nano: int) -> datetime:
    """Nanoseconds since the epoch, to the microsecond (what Postgres keeps)."""
    return EPOCH + timedelta(microseconds=unix_nano // 1000)


def _cut(value: Any, width: int) -> str | None:
    """A version string as stored: text only, at most `width` characters, None when absent."""
    clean = _text(value, width) if isinstance(value, str) else ""
    return clean or None


def _row(app: str, version: dict[str, str | None], span: OtlpSpan) -> dict[str, Any]:
    return {
        "trace_id": span.trace_id.hex(),
        "span_id": span.span_id.hex(),
        "parent_span_id": span.parent_span_id.hex() or None,
        "app": app,
        **version,
        "name": _text(span.name, SPAN_NAME_MAX),
        "kind": KINDS.get(span.kind, "unspecified"),
        "start_time": _time(span.start_time_unix_nano),
        "end_time": _time(span.end_time_unix_nano),
        "status": STATUSES.get(span.status.code, "unset"),
        "status_message": _text(span.status.message, STATUS_MESSAGE_MAX) or None,
        "attributes": _attributes(span.attributes),
        "events": [
            {
                "name": _text(event.name, SPAN_NAME_MAX),
                "time": _time(event.time_unix_nano).isoformat(),
                "attributes": _attributes(event.attributes),
            }
            for event in span.events
        ],
    }


def decode(body: bytes, app: str | None = None) -> list[dict[str, Any]]:
    """The `spans` rows of an OTLP trace export, for `app` only, or every allowed app when None.

    Raises DecodeError for a body that is not an export and ExportTooLarge for one of more than
    MAX_EXPORT_SPANS spans (counted over every app, kept or not)."""
    export = ExportTraceServiceRequest()
    export.ParseFromString(body)
    spans = sum(len(scope.spans) for rs in export.resource_spans for scope in rs.scope_spans)
    if spans > MAX_EXPORT_SPANS:
        raise ExportTooLarge
    rows = []
    for resource_spans in export.resource_spans:
        resource = _attributes(resource_spans.resource.attributes)
        name = resource.get("service.name")
        if name not in ALLOWED_APPS or (app is not None and name != app):
            continue
        app_version = _cut(resource.get("service.version"), APP_VERSION_MAX)
        for scope in resource_spans.scope_spans:
            # The resource's schema URL, else the instrumentation scope's.
            version = {
                "app_version": app_version,
                "schema_url": _cut(resource_spans.schema_url or scope.schema_url, SCHEMA_URL_MAX),
            }
            rows.extend(_row(name, version, span) for span in scope.spans)
    return rows


async def store_spans(engine: AsyncEngine, rows: list[dict[str, Any]]) -> int:
    """Insert the rows into `spans`; returns how many were new.

    A span already stored is left alone, so an exporter's retry changes nothing. Nothing else
    happens on the way in: which traces failed is decided by the trace judge, in a run.
    """
    async with engine.begin() as conn:
        new = await conn.execute(
            insert(Span).on_conflict_do_nothing().returning(Span.span_id), rows
        )
        return len(new.all())


def _too_large() -> HTTPException:
    return HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE,
        f"an export is at most {MAX_EXPORT_BYTES} bytes and {MAX_EXPORT_SPANS} spans",
    )


async def _read_body(request: Request) -> bytes:
    """The body, refused with a 413 as soon as it passes MAX_EXPORT_BYTES, whether or not the
    sender declared its length."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_EXPORT_BYTES:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_EXPORT_BYTES:
            raise _too_large()
    return bytes(body)


@router.post("/traces")
async def receive_traces(request: Request, app: Annotated[str, Depends(sending_app)]) -> Response:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != PROTOBUF:
        raise HTTPException(415, f"send {PROTOBUF}")
    not_after = datetime.now(UTC) + timedelta(seconds=MAX_CLOCK_SKEW_S)
    try:
        rows = decode(await _read_body(request), app)
    except DecodeError:
        raise HTTPException(400, "not an OTLP trace export") from None
    except ExportTooLarge:
        raise _too_large() from None
    rows = [row for row in rows if row["start_time"] <= not_after]
    if rows:
        try:
            await store_spans(request.app.state.engine, rows)
        except Exception as exc:
            # By type only: a database error quotes the row, and so span content.
            logger.error("storing spans failed: %s", type(exc).__name__)
            raise HTTPException(503, "trace store unavailable") from None
    return Response(ExportTraceServiceResponse().SerializeToString(), media_type=PROTOBUF)
