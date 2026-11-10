"""The runs API against a fake trace session, so no trace server subprocess is started."""

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from agent.graph import build_graph
from agent.schemas import Proposal
from api import ui_spec
from main import app
from runs import Runs
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


def use_runs(traces: FakeTraces | None = None, model=None, open_traces=None) -> None:
    """Give the app a runs module over `traces` (or a session factory of the test's own).

    The embedder is offline, so the real model is never downloaded, and the chat model is a fake
    that is never called unless the test passes a diagnoser.
    """

    @asynccontextmanager
    async def session():
        yield traces or FakeTraces()

    app.state.runs = Runs(
        app.state.graph, HashingEmbedder(), model or fake_model(), open_traces or session
    )


PHI = "patient John Doe"  # stands in for clinical text that must never reach a response or a log


def two_failures(**span_overrides) -> FakeTraces:
    trees = {t: span_tree(t, **span_overrides) for t in ("tr_1", "tr_2")}
    return FakeTraces([summary("tr_1"), summary("tr_2")], trees)


def use_diagnosed_run(**span_overrides) -> None:
    """Two failures in one cluster, c0, which the fake diagnoser diagnoses."""
    use_runs(two_failures(**span_overrides), fake_diagnoser(DIAGNOSIS))


@asynccontextmanager
async def broken_session():
    raise RuntimeError(f"span says: {PHI}")
    yield


@pytest.fixture
async def client():
    # ASGITransport does not run the lifespan, so attach an in-memory graph to the app here.
    app.state.graph = build_graph(InMemorySaver(), InMemoryStore())
    use_runs()
    app.state.ui_spec_model = fake_model()  # its call fails, so no message gets a UI spec
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """(event name, JSON data) per event."""
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


async def post_stream(client, body: dict | None = None) -> httpx.Response:
    return await client.post("/v1/runs/stream", json=body or {"target_app": "medas"})


async def stream(client, body: dict | None = None) -> list[tuple[str, dict]]:
    response = await post_stream(client, body)
    assert response.status_code == 200
    return parse_sse(response.text)


async def start(client) -> str:
    """Run a triage to its last message and return the run id."""
    events = await stream(client)
    return events[0][1]["run_id"]


class ExplodingTraces(FakeTraces):
    async def search_failed_traces(self, query):
        raise RuntimeError(f"span says: {PHI}")


# --- POST /v1/runs/stream


@pytest.mark.anyio
async def test_stream_reports_progress_and_stops_at_the_review_with_counts(client):
    use_diagnosed_run()
    response = await post_stream(client)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)

    names = [name for name, _ in events]
    assert names[0] == "run_started" and names[-1] == "review_required"
    assert set(names[1:-1]) == {"progress", "proposal"}
    assert events[1][1]["node"] == "collect_traces"
    progress = [data for name, data in events if name == "progress"]
    assert "tr_1" not in json.dumps(progress) and "tr_2" not in json.dumps(progress)
    # The review node pauses, it does not finish; nothing after it has run.
    assert (progress[-1]["node"], progress[-1]["event"]) == ("human_review", "node_paused")
    assert "apply_actions" not in {p["node"] for p in progress}

    started, summary_ = events[0][1], dict(events[-1][1])
    assert UUID(summary_["run_id"]) and started == {"run_id": summary_.pop("run_id")}
    assert summary_ == {
        "failed_traces": 2,
        "clusters": 1,
        "unclustered": 0,
        "diagnoses": 1,
        "diagnosis_failures": 0,
        "proposals": 1,
        "actions_log": [],
    }


@pytest.mark.anyio
async def test_a_run_with_no_failures_completes_without_a_review(client):
    events = await stream(client)
    names = [name for name, _ in events]
    assert names[-1] == "run_completed" and "proposal" not in names
    assert events[-1][1]["failed_traces"] == 0


@pytest.mark.anyio
async def test_each_run_is_its_own_checkpointed_thread(client):
    use_runs(FakeTraces([summary("tr_1")]))
    first = await start(client)
    use_runs(FakeTraces())
    second = await start(client)

    async def failed_traces(run_id: str) -> int:
        return (await client.get(f"/v1/runs/{run_id}")).json()["summary"]["failed_traces"]

    assert first != second
    assert await failed_traces(first) == 1
    assert await failed_traces(second) == 0


@pytest.mark.anyio
async def test_window_reaches_the_trace_query(client):
    fake = FakeTraces()
    use_runs(fake)
    await stream(
        client,
        {"target_app": "medas", "since": "2026-11-05T09:30:00Z", "until": "2026-11-06T00:00:00Z"},
    )
    [query] = fake.queries
    assert query.since is not None and query.since.isoformat() == "2026-11-05T09:30:00+00:00"
    assert query.until is not None and query.until.isoformat() == "2026-11-06T00:00:00+00:00"


@pytest.mark.anyio
async def test_naive_since_is_rejected(client):
    body = {"target_app": "medas", "since": "2026-11-05T09:30:00"}
    assert (await post_stream(client, body)).status_code == 422


@pytest.mark.anyio
async def test_the_sync_run_endpoint_is_gone(client):
    assert (await client.post("/v1/runs", json={"target_app": "medas"})).status_code == 404


@pytest.mark.anyio
async def test_stream_sends_each_drafted_proposal_between_the_progress_and_the_end(client):
    use_diagnosed_run(attributes={"patient": PHI})
    response = await post_stream(client)
    events = parse_sse(response.text)

    names = [name for name, _ in events]
    first = names.index("proposal")
    assert "progress" not in names[first:]
    assert names[first:] == ["proposal"] * (len(names) - first - 1) + ["review_required"]
    proposals = [Proposal.model_validate(data) for name, data in events if name == "proposal"]
    assert len(proposals) == events[-1][1]["proposals"] > 0
    assert all(p.diagnosed and "## Suspected cause" in p.body for p in proposals)
    assert PHI not in response.text  # span attributes never reach the stream


@pytest.mark.anyio
async def test_stream_reports_a_failing_node_then_run_failed_without_details(client):
    use_runs(ExplodingTraces())
    response = await post_stream(client)
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
async def test_stream_that_cannot_open_the_trace_session_returns_502(client):
    use_runs(open_traces=broken_session)
    response = await post_stream(client)
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
async def test_disconnect_from_a_stalled_client_releases_the_trace_session(client):
    released = []

    @asynccontextmanager
    async def session():
        try:
            yield two_failures()
        finally:
            released.append(True)

    use_runs(model=fake_diagnoser(DIAGNOSIS), open_traces=session)
    await run_with_a_stalled_client()
    # No gc.collect() here on purpose: FastAPI's exit stack has to release it, not finalization.
    assert released == [True]


# --- the UI spec behind each stream message

LAYOUT = json.dumps(SPEC)


@pytest.mark.anyio
async def test_stream_sends_the_models_ui_spec_right_behind_every_message(client):
    use_diagnosed_run(attributes={"patient": PHI})
    app.state.ui_spec_model = model = scripted(LAYOUT)
    response = await post_stream(client)
    events = parse_sse(response.text)

    # Message, its spec, message, its spec, ...: a spec describes the event just before it.
    assert [name for name, _ in events[0::2]] == [n for n, _ in events if n != "ui_spec"]
    assert all(name == "ui_spec" for name, _ in events[1::2])
    for (name, _), (_, spec) in zip(events[0::2], events[1::2], strict=True):
        assert spec == {"event": name, "spec": SPEC}
    assert events[-2][0] == "review_required"
    assert len(model.seen) == len(events) // 2
    assert PHI not in response.text and PHI not in str(model.seen)  # no span attributes, ever


@pytest.mark.anyio
async def test_stream_still_sends_every_message_when_the_model_fails(client):
    use_diagnosed_run()  # the UI spec model is the fixture's: it fails
    names = [name for name, _ in await stream(client)]
    assert names[-1] == "review_required" and "proposal" in names
    assert "ui_spec" not in names  # no spec, and nothing in its place


@pytest.mark.anyio
async def test_a_run_past_its_call_limit_gets_no_more_calls_and_no_more_specs(client, monkeypatch):
    use_diagnosed_run()
    monkeypatch.setattr(ui_spec, "MAX_UI_CALLS_PER_RUN", 2)
    app.state.ui_spec_model = model = scripted(LAYOUT)
    names = [name for name, _ in await stream(client)]
    assert len(names) - names.count("ui_spec") > 2
    assert len(model.seen) == 2 and names.count("ui_spec") == 2


@pytest.mark.anyio
async def test_a_failed_run_sends_no_ui_spec_for_run_failed(client):
    use_runs(ExplodingTraces())
    app.state.ui_spec_model = scripted(LAYOUT)
    events = await stream(client)
    assert events[-1] == ("run_failed", {})
    assert events[-2][0] == "ui_spec" and events[-2][1]["event"] == "progress"


# --- GET /v1/runs/{run_id}


@pytest.mark.anyio
async def test_status_of_a_paused_run_is_review_required_with_its_proposals(client):
    use_diagnosed_run(attributes={"patient": PHI})
    run_id = await start(client)

    response = await client.get(f"/v1/runs/{run_id}")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "summary", "proposals"}  # counts and proposals, no raw state
    assert body["status"] == "review_required"
    assert body["summary"]["run_id"] == run_id and body["summary"]["proposals"] == 1
    assert [Proposal.model_validate(p).cluster_id for p in body["proposals"]] == ["c0"]
    assert PHI not in response.text


@pytest.mark.anyio
async def test_status_of_a_run_that_had_nothing_to_review_is_completed(client):
    run_id = await start(client)
    body = (await client.get(f"/v1/runs/{run_id}")).json()
    assert body["status"] == "completed" and body["proposals"] == []


@pytest.mark.anyio
async def test_an_unknown_run_is_404_and_a_malformed_id_422(client):
    assert (await client.get(f"/v1/runs/{uuid4()}")).status_code == 404
    assert (await client.get("/v1/runs/not-a-uuid")).status_code == 422
    review = {"decisions": {"c0": "approve"}}
    assert (await client.post(f"/v1/runs/{uuid4()}/review", json=review)).status_code == 404


# --- POST /v1/runs/{run_id}/review


@pytest.mark.anyio
async def test_approving_resumes_the_run_through_apply_actions(client):
    use_diagnosed_run()
    run_id = await start(client)

    response = await client.post(f"/v1/runs/{run_id}/review", json={"decisions": {"c0": "approve"}})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["summary"]["actions_log"] == ["[dry-run] create_issue c0"]
    assert (await client.get(f"/v1/runs/{run_id}")).json()["status"] == "completed"


@pytest.mark.anyio
async def test_rejecting_everything_ends_the_run_without_any_action(client):
    use_diagnosed_run()
    run_id = await start(client)
    response = await client.post(f"/v1/runs/{run_id}/review", json={"decisions": {"c0": "reject"}})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["summary"]["actions_log"] == []


@pytest.mark.anyio
async def test_a_run_is_reviewed_once(client):
    use_diagnosed_run()
    run_id = await start(client)
    review = {"decisions": {"c0": "reject"}}
    assert (await client.post(f"/v1/runs/{run_id}/review", json=review)).status_code == 200

    again = await client.post(f"/v1/runs/{run_id}/review", json={"decisions": {"c0": "approve"}})
    assert again.status_code == 409
    assert (await client.get(f"/v1/runs/{run_id}")).json()["summary"]["actions_log"] == []


@pytest.mark.anyio
async def test_a_run_with_nothing_to_review_cannot_be_reviewed(client):
    run_id = await start(client)
    response = await client.post(f"/v1/runs/{run_id}/review", json={"decisions": {}})
    assert response.status_code == 409


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("decisions", "detail"),
    [
        ({}, {"missing": ["c0"], "unknown": []}),
        ({"c0": "approve", "c9": "reject"}, {"missing": [], "unknown": ["c9"]}),
    ],
)
async def test_a_review_that_does_not_match_the_proposals_is_422_and_changes_nothing(
    client, decisions, detail
):
    use_diagnosed_run()
    run_id = await start(client)
    response = await client.post(f"/v1/runs/{run_id}/review", json={"decisions": decisions})
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert (await client.get(f"/v1/runs/{run_id}")).json()["status"] == "review_required"


@pytest.mark.anyio
async def test_a_decision_other_than_approve_or_reject_is_422(client):
    use_diagnosed_run()
    run_id = await start(client)
    response = await client.post(f"/v1/runs/{run_id}/review", json={"decisions": {"c0": "maybe"}})
    assert response.status_code == 422
    assert (await client.get(f"/v1/runs/{run_id}")).json()["status"] == "review_required"


@pytest.mark.anyio
async def test_the_review_opens_no_trace_session(client):
    opened = []

    @asynccontextmanager
    async def session():
        opened.append(True)
        yield two_failures()

    use_runs(model=fake_diagnoser(DIAGNOSIS), open_traces=session)
    run_id = await start(client)
    assert opened == [True]
    review = {"decisions": {"c0": "approve"}}
    assert (await client.post(f"/v1/runs/{run_id}/review", json=review)).status_code == 200
    assert opened == [True]
