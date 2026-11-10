"""The trace collector: OTLP over HTTP in, rows in `spans` out.

    POST /v1/traces   Content-Type: application/x-protobuf   (an ExportTraceServiceRequest)

Binary protobuf, uncompressed: the OTel exporters' default. Spans of an app outside
ALLOWED_APPS are not stored. Nothing here logs a span.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span as OtlpSpan
from opentelemetry.proto.trace.v1.trace_pb2 import Status
from sqlalchemy.dialects.postgresql import insert

from db.models import Span
from trace_store.const import ALLOWED_APPS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")

PROTOBUF = "application/x-protobuf"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# OTLP's enum numbers as words: SPAN_KIND_SERVER is "server", STATUS_CODE_ERROR is "error".
KINDS = {v: name.removeprefix("SPAN_KIND_").lower() for name, v in OtlpSpan.SpanKind.items()}
STATUSES = {v: name.removeprefix("STATUS_CODE_").lower() for name, v in Status.StatusCode.items()}


def _value(value: AnyValue) -> Any:
    """An attribute value as a plain JSON value; scalars and arrays only."""
    match value.WhichOneof("value"):
        case "string_value":
            return value.string_value
        case "bool_value":
            return value.bool_value
        case "int_value":
            return value.int_value
        case "double_value":
            return value.double_value
        case "array_value":
            return [_value(item) for item in value.array_value.values]
        case _:
            return None


def _attributes(pairs: Iterable[KeyValue]) -> dict[str, Any]:
    return {pair.key: _value(pair.value) for pair in pairs}


def _time(unix_nano: int) -> datetime:
    """Nanoseconds since the epoch, to the microsecond (what Postgres keeps)."""
    return EPOCH + timedelta(microseconds=unix_nano // 1000)


def _row(app: str, span: OtlpSpan) -> dict[str, Any]:
    return {
        "trace_id": span.trace_id.hex(),
        "span_id": span.span_id.hex(),
        "parent_span_id": span.parent_span_id.hex() or None,
        "app": app,
        "name": span.name,
        "kind": KINDS.get(span.kind, "unspecified"),
        "start_time": _time(span.start_time_unix_nano),
        "end_time": _time(span.end_time_unix_nano),
        "status": STATUSES.get(span.status.code, "unset"),
        "status_message": span.status.message or None,
        "attributes": _attributes(span.attributes),
        "events": [
            {
                "name": event.name,
                "time": _time(event.time_unix_nano).isoformat(),
                "attributes": _attributes(event.attributes),
            }
            for event in span.events
        ],
    }


def decode(body: bytes) -> list[dict[str, Any]]:
    """The `spans` rows of an OTLP trace export, for the allowed apps only. Raises DecodeError."""
    export = ExportTraceServiceRequest()
    export.ParseFromString(body)
    rows = []
    for resource_spans in export.resource_spans:
        app = _attributes(resource_spans.resource.attributes).get("service.name")
        if app not in ALLOWED_APPS:
            continue
        for scope in resource_spans.scope_spans:
            rows.extend(_row(app, span) for span in scope.spans)
    return rows


@router.post("/traces")
async def receive_traces(request: Request) -> Response:
    if request.headers.get("content-type") != PROTOBUF:
        raise HTTPException(415, f"send {PROTOBUF}")
    try:
        rows = decode(await request.body())
    except DecodeError:
        raise HTTPException(400, "not an OTLP trace export") from None
    if rows:
        try:
            async with request.app.state.engine.begin() as conn:
                # A span already stored is left alone, so an exporter's retry changes nothing.
                await conn.execute(insert(Span).on_conflict_do_nothing(), rows)
        except Exception as exc:
            # By type only: a database error quotes the row, and so span content.
            logger.error("storing spans failed: %s", type(exc).__name__)
            raise HTTPException(503, "trace store unavailable") from None
    return Response(ExportTraceServiceResponse().SerializeToString(), media_type=PROTOBUF)
