"""The trace collector: decoding an OTLP export, and POST /v1/traces."""

from datetime import UTC, datetime

import httpx
import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.trace.v1.trace_pb2 import Span as OtlpSpan
from opentelemetry.proto.trace.v1.trace_pb2 import Status
from sqlalchemy import text

from api.traces import PROTOBUF, decode
from main import app
from trace_store.const import APP_VERSION_MAX

TRACE_ID = bytes.fromhex("0af7651916cd43dd8448eb211c80319c")
ROOT_ID = bytes.fromhex("b7ad6b7169203331")
CHILD_ID = bytes.fromhex("00f067aa0ba902b7")
START_NS = 1_793_000_000_123_456_789
START = datetime(2026, 10, 26, 7, 33, 20, 123456, tzinfo=UTC)


def export(service: str = "medas", version: str | None = None, schema: str = "") -> bytes:
    """An export of one trace: a root span and an errored retrieval span below it."""
    request = ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add(schema_url=schema)
    name = resource_spans.resource.attributes.add(key="service.name")
    name.value.string_value = service
    if version is not None:
        resource_spans.resource.attributes.add(key="service.version").value.string_value = version
    spans = resource_spans.scope_spans.add().spans

    spans.add(
        trace_id=TRACE_ID,
        span_id=ROOT_ID,
        name="request",
        kind=OtlpSpan.SPAN_KIND_SERVER,
        start_time_unix_nano=START_NS,
        end_time_unix_nano=START_NS + 2_000_000_000,
    )
    child = spans.add(
        trace_id=TRACE_ID,
        span_id=CHILD_ID,
        parent_span_id=ROOT_ID,
        name="retrieval",
        start_time_unix_nano=START_NS + 1_000_000,
        end_time_unix_nano=START_NS + 5_000_000,
        status=Status(code=Status.STATUS_CODE_ERROR, message="no documents"),
    )
    child.attributes.add(key="gen_ai.operation.name").value.string_value = "execute_tool"
    child.attributes.add(key="retrieval.count").value.int_value = 0
    child.attributes.add(key="gen_ai.system").value.string_value = "openrouter"
    tags = child.attributes.add(key="tags").value.array_value
    tags.values.add().string_value = "a"
    tags.values.add().bool_value = True
    event = child.events.add(name="exception", time_unix_nano=START_NS + 4_000_000)
    event.attributes.add(key="exception.type").value.string_value = "EmptyRetrieval"
    return request.SerializeToString()


def test_an_export_becomes_one_row_per_span():
    root, child = decode(export())
    assert root == {
        "trace_id": TRACE_ID.hex(),
        "span_id": ROOT_ID.hex(),
        "parent_span_id": None,
        "app": "medas",
        "app_version": None,
        "schema_url": None,
        "name": "request",
        "kind": "server",
        "start_time": START,
        "end_time": START.replace(second=22),
        "status": "unset",
        "status_message": None,
        "attributes": {},
        "events": [],
    }
    assert (child["parent_span_id"], child["kind"]) == (ROOT_ID.hex(), "unspecified")
    assert (child["status"], child["status_message"]) == ("error", "no documents")
    assert child["attributes"] == {
        "gen_ai.operation.name": "execute_tool",
        "retrieval.count": 0,
        "gen_ai.system": "openrouter",
        "tags": ["a", True],
    }
    assert child["events"] == [
        {
            "name": "exception",
            "time": "2026-10-26T07:33:20.127456+00:00",
            "attributes": {"exception.type": "EmptyRetrieval"},
        }
    ]


def test_every_span_keeps_the_app_version_and_the_schema_url():
    schema = "https://opentelemetry.io/schemas/1.37.0"
    rows = decode(export(version="2.3.1", schema=schema))
    assert {(row["app_version"], row["schema_url"]) for row in rows} == {("2.3.1", schema)}


def test_a_version_too_long_is_cut_to_the_column():
    (root, _) = decode(export(version="v" * 500))
    assert root["app_version"] == "v" * APP_VERSION_MAX


def test_spans_of_an_app_that_is_not_allowed_are_left_out():
    assert decode(export("someone-else")) == []


async def post(client, body: bytes, content_type: str = PROTOBUF) -> httpx.Response:
    return await client.post("/v1/traces", content=body, headers={"content-type": content_type})


@pytest.mark.anyio
async def test_only_protobuf_is_taken(collector):
    assert (await post(collector, b"{}", "application/json")).status_code == 415


@pytest.mark.anyio
async def test_a_body_that_is_not_an_export_is_refused(collector):
    assert (await post(collector, b"\xff\xff\xff")).status_code == 400


@pytest.mark.anyio
async def test_an_export_of_another_app_is_accepted_and_stores_nothing(collector):
    # No engine on the app here: reaching the database would fail the request.
    response = await post(collector, export("someone-else"))
    assert response.status_code == 200
    assert response.headers["content-type"] == PROTOBUF
    ExportTraceServiceResponse().ParseFromString(response.content)


@pytest.mark.anyio
async def test_an_export_is_stored_and_a_retry_changes_nothing(collector, spans_engine):
    for _ in range(2):  # the second one is the exporter's retry
        assert (await post(collector, export())).status_code == 200
    async with spans_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT span_id, start_time, attributes FROM spans"))).all()
    # Once each, with the timestamp and the JSON as decoded.
    assert sorted(tuple(row) for row in rows) == sorted(
        (row["span_id"], row["start_time"], row["attributes"]) for row in decode(export())
    )


@pytest.mark.anyio
async def test_a_store_that_fails_is_a_503_with_no_detail(collector):
    class Broken:
        def begin(self):
            raise RuntimeError("row content")

    app.state.engine = Broken()
    try:
        response = await post(collector, export())
    finally:
        del app.state.engine
    assert response.status_code == 503
    assert "row content" not in response.text
