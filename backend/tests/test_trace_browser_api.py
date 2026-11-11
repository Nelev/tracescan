"""The trace browser API: GET /v1/traces and GET /v1/traces/{trace_id}. Needs TEST_DATABASE_URL."""

import pytest
from sqlalchemy import text

from api.traces import decode
from api.traces import store_spans as store
from main import app
from tests.test_traces_api import CHILD_ID, ROOT_ID, START, TRACE_ID, export
from trace_store.const import REDACTED

FAILED = TRACE_ID.hex()
HEALTHY = "a" * 32
OTHER_APP = "b" * 32


@pytest.fixture
async def browser(collector, spans_engine, reader):
    """The app's HTTP client with the reader set, over one failed, one healthy, one foreign trace."""
    root, child = decode(export())
    healthy = {**root, "trace_id": HEALTHY, "start_time": START.replace(hour=8)}
    healthy["end_time"] = healthy["start_time"].replace(second=21)
    other_app = [{**span, "trace_id": OTHER_APP, "app": "someone-else"} for span in (root, child)]
    await store(spans_engine, [root, child, healthy, *other_app])
    app.state.trace_reader = reader
    yield collector
    del app.state.trace_reader


@pytest.mark.anyio
async def test_the_list_holds_failed_and_healthy_traces_newest_first(browser):
    response = await browser.get("/v1/traces")
    assert response.status_code == 200
    healthy, failed = response.json()

    assert (healthy["trace_id"], healthy["failed"], healthy["spans"]) == (HEALTHY, False, 1)
    assert healthy["min_score"] == 1.0
    assert healthy["failing_span_id"] is None and healthy["failing_check"] is None

    assert (failed["trace_id"], failed["failed"], failed["spans"]) == (FAILED, True, 2)
    assert (failed["min_score"], failed["duration_ms"]) == (0.0, 2000.0)
    assert (failed["failing_span_id"], failed["failing_span_name"]) == (CHILD_ID.hex(), "retrieval")
    assert (failed["failing_check"], failed["error_type"]) == ("tool_error", "EmptyRetrieval")
    # Names only: no status message or attribute value in a row.
    assert "no documents" not in response.text


@pytest.mark.anyio
async def test_the_list_filters(browser):
    async def ids(**params) -> list[str]:
        response = await browser.get("/v1/traces", params=params)
        assert response.status_code == 200
        return [row["trace_id"] for row in response.json()]

    assert await ids(failed_only="true") == [FAILED]
    assert await ids(limit=1) == [HEALTHY]
    assert await ids(since=START.replace(hour=8).isoformat()) == [HEALTHY]
    assert await ids(until=START.replace(hour=8).isoformat()) == [FAILED]
    assert await ids(app="someone-else") == []
    assert (await browser.get("/v1/traces", params={"limit": 0})).status_code == 422


@pytest.mark.anyio
async def test_an_unscored_trace_is_listed_without_a_score(browser, spans_engine):
    async with spans_engine.begin() as conn:
        await conn.execute(text("DELETE FROM scores WHERE trace_id = :id"), {"id": HEALTHY})

    (row,) = [r for r in (await browser.get("/v1/traces")).json() if r["trace_id"] == HEALTHY]
    assert (row["min_score"], row["failed"]) == (None, False)


@pytest.mark.anyio
async def test_a_trace_comes_back_as_a_sanitized_tree_with_its_scores(browser):
    response = await browser.get(f"/v1/traces/{FAILED}")
    assert response.status_code == 200
    detail = response.json()

    assert (detail["trace_id"], detail["min_score"], detail["failed"]) == (FAILED, 0.0, True)
    scores = {s["evaluator"]: (s["value"], s["span_id"]) for s in detail["scores"]}
    # The request went on after the failed tool call: only the tool check blames a span.
    assert scores["tool_error"] == (0.0, CHILD_ID.hex())
    assert scores["request_failed"] == (1.0, None)
    # The server applies the threshold, so the client never repeats it.
    assert {s["evaluator"]: s["failed"] for s in detail["scores"]} == {
        "request_failed": False,
        "tool_error": True,
    }
    tree = detail["tree"]
    assert (tree["span_id"], tree["name"]) == (ROOT_ID.hex(), "request")
    (child,) = tree["children"]
    assert child["status_message"] == "no documents"
    # Allowlisted keys keep their value; any other key is redacted.
    assert child["attributes"]["gen_ai.system"] == "openrouter"
    assert child["attributes"]["tags"] == REDACTED
    assert child["events"][0]["attributes"] == {"exception.type": "EmptyRetrieval"}


@pytest.mark.anyio
async def test_unknown_foreign_or_malformed_ids_are_refused(browser):
    assert (await browser.get(f"/v1/traces/{'c' * 32}")).status_code == 404
    assert (await browser.get(f"/v1/traces/{OTHER_APP}")).status_code == 404
    assert (await browser.get("/v1/traces/not%20an%20id")).status_code == 422
