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
from agent.schemas import Proposal
from api import runs
from main import app
from tests.fakes import (
    DIAGNOSIS,
    SPEC,
    FakeTraces,
    HashingEmbedder,
    fake_diagnoser,
    fake_model,
    scripted,
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
    app.state.ui_spec_model = fake_model()  # its call fails, so no message gets a UI spec
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
    assert set(names[1:-1]) == {"progress", "proposal"}
    assert events[1][1]["node"] == "collect_traces"
    progress = json.dumps([data for name, data in events if name == "progress"])
    assert "tr_1" not in progress and "tr_2" not in progress  # no trace content in progress

    started, completed = events[0][1], events[-1][1]
    sync = (await client.post("/v1/runs", json=body)).json()
    assert UUID(completed["run_id"]) and started == {"run_id": completed["run_id"]}
    assert {**completed, "run_id": None} == {**sync, "run_id": None}


@pytest.mark.anyio
async def test_stream_sends_each_drafted_proposal_between_the_progress_and_the_end(
    client, monkeypatch
):
    trees = {t: span_tree(t, attributes={"patient": PHI}) for t in ("tr_1", "tr_2")}
    use_traces(monkeypatch, FakeTraces([summary("tr_1"), summary("tr_2")], trees))
    app.state.model = fake_diagnoser(DIAGNOSIS)
    response = await client.post("/v1/runs/stream", json={"target_app": "medas"})
    events = parse_sse(response.text)

    names = [name for name, _ in events]
    first = names.index("proposal")
    assert "progress" not in names[first:]
    assert names[first:] == ["proposal"] * (len(names) - first - 1) + ["run_completed"]
    proposals = [Proposal.model_validate(data) for name, data in events if name == "proposal"]
    assert len(proposals) == events[-1][1]["proposals"] > 0
    assert all(p.diagnosed and "## Suspected cause" in p.body for p in proposals)
    assert PHI not in response.text  # span attributes never reach the stream


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


async def run_with_a_stalled_client() -> None:
    """POST a run to the app as a client that reads nothing and then goes away."""
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
    # client; that is the framework's, so it is ignored here. What matters is what is released.
    with contextlib.suppress(BaseExceptionGroup):
        await app(scope, receive, send)


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
    await run_with_a_stalled_client()
    # No gc.collect() here on purpose: FastAPI's exit stack has to release it, not finalization.
    assert released == [True]


LAYOUT = json.dumps(SPEC)


@pytest.mark.anyio
async def test_stream_sends_the_models_ui_spec_right_behind_every_message(client, monkeypatch):
    trees = {t: span_tree(t, attributes={"patient": PHI}) for t in ("tr_1", "tr_2")}
    use_traces(monkeypatch, FakeTraces([summary("tr_1"), summary("tr_2")], trees))
    app.state.model = fake_diagnoser(DIAGNOSIS)
    app.state.ui_spec_model = model = scripted(LAYOUT)
    response = await client.post("/v1/runs/stream", json={"target_app": "medas"})
    events = parse_sse(response.text)

    # Message, its spec, message, its spec, ...: a spec describes the event just before it.
    assert [name for name, _ in events[0::2]] == [n for n, _ in events if n != "ui_spec"]
    assert all(name == "ui_spec" for name, _ in events[1::2])
    for (name, _), (_, spec) in zip(events[0::2], events[1::2], strict=True):
        assert spec == {"event": name, "spec": SPEC}
    assert events[-2][0] == "run_completed"
    assert len(model.seen) == len(events) // 2
    assert PHI not in response.text and PHI not in str(model.seen)  # no span attributes, ever


@pytest.mark.anyio
async def test_stream_still_sends_every_message_when_the_model_fails(client, monkeypatch):
    trees = {t: span_tree(t) for t in ("tr_1", "tr_2")}
    use_traces(monkeypatch, FakeTraces([summary("tr_1"), summary("tr_2")], trees))
    app.state.model = fake_diagnoser(DIAGNOSIS)  # the UI spec model is the fixture's: it fails
    events = parse_sse((await client.post("/v1/runs/stream", json={"target_app": "medas"})).text)

    names = [name for name, _ in events]
    assert names[-1] == "run_completed" and "proposal" in names
    assert "ui_spec" not in names  # no spec, and nothing in its place


@pytest.mark.anyio
async def test_a_run_past_its_call_limit_gets_no_more_calls_and_no_more_specs(client, monkeypatch):
    use_traces(monkeypatch, two_failures())
    monkeypatch.setattr(runs, "MAX_UI_CALLS_PER_RUN", 2)
    app.state.model = fake_diagnoser(DIAGNOSIS)
    app.state.ui_spec_model = model = scripted(LAYOUT)
    events = parse_sse((await client.post("/v1/runs/stream", json={"target_app": "medas"})).text)

    names = [name for name, _ in events]
    assert len(names) - names.count("ui_spec") > 2
    assert len(model.seen) == 2 and names.count("ui_spec") == 2


@pytest.mark.anyio
async def test_a_failed_run_sends_no_ui_spec_for_run_failed(client, monkeypatch):
    use_traces(monkeypatch, ExplodingTraces())
    app.state.ui_spec_model = scripted(LAYOUT)
    events = parse_sse((await client.post("/v1/runs/stream", json={"target_app": "medas"})).text)
    assert events[-1] == ("run_failed", {})
    assert events[-2][0] == "ui_spec" and events[-2][1]["event"] == "progress"
