"""POST /v1/runs against a fake trace client, so no trace server subprocess is started."""

from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from agent.graph import build_graph
from api import runs
from main import app
from tests.fakes import FakeTraces, summary


def use_traces(monkeypatch, fake: FakeTraces) -> None:
    @asynccontextmanager
    async def session():
        yield fake

    monkeypatch.setattr(runs, "TraceClient", session)


@pytest.fixture
async def client():
    # ASGITransport does not run the lifespan, so attach an in-memory graph to the app here.
    app.state.graph = build_graph(InMemorySaver(), InMemoryStore())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.anyio
async def test_run_returns_counts_not_raw_traces(client, monkeypatch):
    use_traces(monkeypatch, FakeTraces([summary("tr_1"), summary("tr_2")]))
    response = await client.post("/v1/runs", json={"target_app": "medas"})
    assert response.status_code == 200
    body = response.json()
    assert UUID(body.pop("run_id"))
    assert body == {
        "failed_traces": 2,
        "clusters": 1,
        "diagnoses": 1,
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
    @asynccontextmanager
    async def broken():
        raise RuntimeError("span says: patient John Doe")
        yield

    monkeypatch.setattr(runs, "TraceClient", broken)
    response = await client.post("/v1/runs", json={"target_app": "medas"})
    assert response.status_code == 502
    assert response.json() == {"detail": "triage run failed"}
