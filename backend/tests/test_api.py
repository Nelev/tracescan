"""POST /v1/runs against a fake trace client, so no trace server subprocess is started."""

from contextlib import asynccontextmanager

import httpx
import pytest

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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.anyio
async def test_run_returns_counts_not_raw_traces(client, monkeypatch):
    use_traces(monkeypatch, FakeTraces([summary("tr_1"), summary("tr_2")]))
    response = await client.post("/v1/runs", json={"target_app": "medas"})
    assert response.status_code == 200
    assert response.json() == {
        "failed_traces": 2,
        "clusters": 1,
        "diagnoses": 1,
        "proposals": 1,
        "actions_log": ["[dry-run] create_issue c0"],
    }


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
