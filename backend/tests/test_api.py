"""POST /v1/runs against a fake trace client, so no trace server subprocess is started."""

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from agent.graph import build_graph
from api import runs
from main import app
from tests.fakes import (
    DIAGNOSIS,
    FakeTraces,
    HashingEmbedder,
    fake_diagnoser,
    fake_model,
    span_tree,
    summary,
)


def use_traces(monkeypatch, fake: FakeTraces) -> None:
    @asynccontextmanager
    async def session():
        yield fake

    monkeypatch.setattr(runs, "TraceClient", session)


PHI = "patient John Doe"  # stands in for clinical text that must never reach a response or a log


def two_failures() -> FakeTraces:
    return FakeTraces(
        [summary("tr_1"), summary("tr_2")], {t: span_tree(t) for t in ("tr_1", "tr_2")}
    )


def use_broken_session(monkeypatch) -> None:
    @asynccontextmanager
    async def broken():
        raise RuntimeError(f"span says: {PHI}")
        yield

    monkeypatch.setattr(runs, "TraceClient", broken)


@pytest.fixture
async def client():
    # ASGITransport does not run the lifespan, so attach an in-memory graph to the app here.
    app.state.graph = build_graph(InMemorySaver(), InMemoryStore())
    app.state.embedder = HashingEmbedder()  # offline: the real model is never downloaded in tests
    app.state.model = fake_model()  # never called; tests that diagnose set their own
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.anyio
async def test_run_returns_counts_not_raw_traces(client, monkeypatch):
    use_traces(monkeypatch, two_failures())
    app.state.model = fake_diagnoser(DIAGNOSIS)
    response = await client.post("/v1/runs", json={"target_app": "medas"})
    assert response.status_code == 200
    body = response.json()
    assert UUID(body.pop("run_id"))
    assert body == {
        "failed_traces": 2,
        "clusters": 1,
        "unclustered": 0,
        "diagnoses": 1,
        "diagnosis_failures": 0,
        "proposals": 1,
        "actions_log": ["[dry-run] create_issue c0"],
    }


@pytest.mark.anyio
async def test_each_run_is_its_own_checkpointed_thread(client, monkeypatch):
    use_traces(monkeypatch, FakeTraces([summary("tr_1")]))
    first = (await client.post("/v1/runs", json={"target_app": "medas"})).json()["run_id"]
    use_traces(monkeypatch, FakeTraces())
    second = (await client.post("/v1/runs", json={"target_app": "medas"})).json()["run_id"]

    async def saved_failed_traces(run_id: str) -> list:
        snapshot = await app.state.graph.aget_state({"configurable": {"thread_id": run_id}})
        return snapshot.values["failed_traces"]

    assert len(await saved_failed_traces(first)) == 1
    assert await saved_failed_traces(second) == []


@pytest.mark.anyio
async def test_window_reaches_the_trace_query(client, monkeypatch):
    fake = FakeTraces()
    use_traces(monkeypatch, fake)
    body = {"target_app": "medas", "since": "2026-11-05T09:30:00Z", "until": "2026-11-06T00:00:00Z"}
    assert (await client.post("/v1/runs", json=body)).status_code == 200
    [query] = fake.queries
    assert query.since is not None and query.since.isoformat() == "2026-11-05T09:30:00+00:00"
    assert query.until is not None and query.until.isoformat() == "2026-11-06T00:00:00+00:00"


@pytest.mark.anyio
async def test_naive_since_is_rejected(client, monkeypatch):
    use_traces(monkeypatch, FakeTraces())
    body = {"target_app": "medas", "since": "2026-11-05T09:30:00"}
    assert (await client.post("/v1/runs", json=body)).status_code == 422


@pytest.mark.anyio
async def test_failing_run_returns_502_without_details(client, monkeypatch):
    use_broken_session(monkeypatch)
    response = await client.post("/v1/runs", json={"target_app": "medas"})
    assert response.status_code == 502
    assert response.json() == {"detail": "triage run failed"}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """(event name, JSON data) per event."""
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


class ExplodingTraces(FakeTraces):
    async def search_failed_traces(self, query):
        raise RuntimeError(f"span says: {PHI}")


@pytest.mark.anyio
async def test_stream_reports_progress_then_the_same_summary_as_the_sync_run(client, monkeypatch):
    use_traces(monkeypatch, two_failures())
    app.state.model = fake_diagnoser(DIAGNOSIS)
    body = {"target_app": "medas"}

    response = await client.post("/v1/runs/stream", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)

    names = [name for name, _ in events]
    assert names[0] == "run_started" and names[-1] == "run_completed"
    assert set(names[1:-1]) == {"progress"}
    assert events[1][1]["node"] == "collect_traces"
    assert "tr_1" not in response.text and "tr_2" not in response.text  # no trace content

    started, completed = events[0][1], events[-1][1]
    sync = (await client.post("/v1/runs", json=body)).json()
    assert UUID(completed["run_id"]) and started == {"run_id": completed["run_id"]}
    assert {**completed, "run_id": None} == {**sync, "run_id": None}


@pytest.mark.anyio
async def test_stream_reports_a_failing_node_then_run_failed_without_details(client, monkeypatch):
    use_traces(monkeypatch, ExplodingTraces())
    response = await client.post("/v1/runs/stream", json={"target_app": "medas"})
    assert response.status_code == 200
    events = parse_sse(response.text)

    names = [name for name, _ in events]
    assert names[0] == "run_started" and names[-1] == "run_failed"
    assert set(names[1:-1]) == {"progress"}
    assert events[-1][1] == {}
    failed = [d["node"] for n, d in events if n == "progress" and d["event"] == "node_failed"]
    assert failed == ["collect_traces"]
    assert "John Doe" not in response.text


@pytest.mark.anyio
async def test_stream_that_cannot_open_the_trace_session_returns_502(client, monkeypatch):
    use_broken_session(monkeypatch)
    response = await client.post("/v1/runs/stream", json={"target_app": "medas"})
    assert response.status_code == 502
    assert response.json() == {"detail": "triage run failed"}


@pytest.mark.anyio
async def test_disconnect_from_a_stalled_client_releases_the_trace_session(client, monkeypatch):
    released = []

    @asynccontextmanager
    async def session():
        try:
            yield two_failures()
        finally:
            released.append(True)

    monkeypatch.setattr(runs, "TraceClient", session)
    app.state.model = fake_diagnoser(DIAGNOSIS)
    payload = json.dumps({"target_app": "medas"}).encode()
    pending = [{"type": "http.request", "body": payload}]

    async def receive():
        if pending:
            return pending.pop()
        await asyncio.sleep(0.3)  # the client reads nothing, then goes away
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            await asyncio.sleep(1)  # a stalled client keeps the producer parked at a yield

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/v1/runs/stream",
        "raw_path": b"/v1/runs/stream",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ],
        "scheme": "http",
        "root_path": "",
    }
    # FastAPI's SSE keepalive task raises BrokenResourceError while tearing down on a stalled
    # client; that is the framework's, so it is ignored here. What matters is the release.
    with contextlib.suppress(BaseExceptionGroup):
        await app(scope, receive, send)
    # No gc.collect() here on purpose: FastAPI's exit stack has to release it, not finalization.
    assert released == [True]
