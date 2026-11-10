"""The runs API against a fake trace session, so no trace server subprocess is started."""

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from agent.actions import OUT_DIR, REGRESSION_FILE
from agent.graph import build_graph
from agent.schemas import Proposal
from api import ui_spec
from main import app, dry_run_setting
from runs import NAME_MAX, Runs
from tests.fakes import (
    DIAGNOSIS,
    SPEC,
    FakeTraces,
    InMemoryRunStore,
    fake_context,
    fake_diagnoser,
    fake_model,
    files_under,
    scripted,
    span_tree,
    summary,
)


def use_runs(traces: FakeTraces | None = None, model=None, open_traces=None) -> None:
    """Give the app a runs module over `traces` (or a session factory of the test's own).

    The context is the shared fake one: an offline embedder, so the real model is never downloaded,
    and a chat model that is never called unless the test passes a diagnoser.
    """

    @asynccontextmanager
    async def session():
        yield traces or FakeTraces()

    app.state.run_store = store = InMemoryRunStore()
    app.state.runs = Runs(
        app.state.graph, fake_context(FakeTraces(), model), open_traces or session, store
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
def out_dir(tmp_path, monkeypatch) -> Path:
    """Where this test's dry run writes: the default `out`, under a working directory of its own."""
    monkeypatch.chdir(tmp_path)
    return tmp_path / OUT_DIR


@pytest.fixture
async def client(out_dir):
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
    # 405, not 404: the path exists again, but only to list runs with GET.
    assert (await client.post("/v1/runs", json={"target_app": "medas"})).status_code == 405


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
async def test_approving_writes_the_issue_and_the_regression_case_as_a_dry_run(client, out_dir):
    use_diagnosed_run()
    run_id = await start(client)
    assert files_under(out_dir) == []  # nothing is written before the review

    response = await client.post(f"/v1/runs/{run_id}/review", json={"decisions": {"c0": "approve"}})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["summary"]["actions_log"]) == 2  # the wording is tested in test_actions
    assert files_under(out_dir) == ["issues/c0.md", REGRESSION_FILE]
    assert "## Suspected cause" in (out_dir / "issues" / "c0.md").read_text()
    assert (await client.get(f"/v1/runs/{run_id}")).json()["status"] == "completed"


@pytest.mark.anyio
async def test_rejecting_everything_ends_the_run_without_writing_anything(client, out_dir):
    use_diagnosed_run()
    run_id = await start(client)
    response = await client.post(f"/v1/runs/{run_id}/review", json={"decisions": {"c0": "reject"}})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["summary"]["actions_log"] == []
    assert files_under(out_dir) == []


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


# --- the DRY_RUN setting


@pytest.mark.parametrize("value", [None, "true", "1", "yes", ""])
def test_dry_run_is_on_unless_the_environment_turns_it_off(monkeypatch, value):
    monkeypatch.delenv("DRY_RUN", raising=False)
    if value is not None:
        monkeypatch.setenv("DRY_RUN", value)
    assert dry_run_setting() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", " False "])
def test_dry_run_is_off_when_the_environment_says_so(monkeypatch, value):
    monkeypatch.setenv("DRY_RUN", value)
    assert dry_run_setting() is False


# --- the record of runs: GET /v1/runs, who started and who reviewed

ANA = {"X-User-Name": "ana"}
BO = {"X-User-Name": "bo"}


async def listed(client) -> list[dict]:
    response = await client.get("/v1/runs")
    assert response.status_code == 200
    return response.json()


@pytest.mark.anyio
async def test_runs_are_listed_newest_first_with_who_started_them_and_no_state(client):
    use_diagnosed_run(attributes={"patient": PHI})
    window = {"target_app": "medas", "since": "2026-11-05T09:00:00Z"}
    first = (await client.post("/v1/runs/stream", json=window, headers=ANA)).text
    second = (await client.post("/v1/runs/stream", json={"target_app": "medas"})).text
    first_id, second_id = (parse_sse(text)[0][1]["run_id"] for text in (first, second))

    runs = await listed(client)
    assert [r["run_id"] for r in runs] == [second_id, first_id]
    assert [r["started_by"] for r in runs] == ["local", "ana"]  # no header: the default name
    assert runs[1]["status"] == "review_required" and runs[1]["ended_at"] is None
    assert runs[1]["since"] == "2026-11-05T09:00:00Z" and runs[1]["until"] is None
    assert (runs[1]["failed_traces"], runs[1]["clusters"], runs[1]["proposals"]) == (2, 1, 1)
    assert set(runs[0]) == {
        "run_id",
        "target_app",
        "since",
        "until",
        "status",
        "started_by",
        "created_at",
        "ended_at",
        "failed_traces",
        "clusters",
        "proposals",
    }
    assert [r["run_id"] for r in (await client.get("/v1/runs?limit=1")).json()] == [second_id]
    assert (await client.get("/v1/runs?limit=0")).status_code == 422


@pytest.mark.anyio
async def test_a_review_is_recorded_with_its_decisions_and_the_reviewer(client):
    use_diagnosed_run()
    run_id = await start(client)
    review = {"decisions": {"c0": "approve"}}
    assert (
        await client.post(f"/v1/runs/{run_id}/review", json=review, headers=BO)
    ).status_code == 200

    (run,) = await listed(client)
    assert run["status"] == "completed" and run["ended_at"] is not None
    (decided,) = await app.state.run_store.reviews(run_id)
    assert (decided.cluster_id, decided.decision, decided.reviewer) == ("c0", "approve", "bo")


@pytest.mark.anyio
async def test_a_review_that_is_refused_records_no_decision(client):
    use_diagnosed_run()
    run_id = await start(client)
    partial = await client.post(f"/v1/runs/{run_id}/review", json={"decisions": {}})
    assert partial.status_code == 422
    assert await app.state.run_store.reviews(run_id) == []
    assert (await listed(client))[0]["status"] == "review_required"


@pytest.mark.anyio
async def test_a_run_another_review_holds_is_refused_and_free_again_when_that_one_fails(client):
    use_diagnosed_run()
    run_id = await start(client)
    review = {"decisions": {"c0": "approve"}}

    with pytest.raises(RuntimeError):
        # A review in another process, which then dies before it is applied.
        async with app.state.run_store.reviewing(run_id, {"c0": "reject"}, "ana"):
            assert (await client.post(f"/v1/runs/{run_id}/review", json=review)).status_code == 409
            assert (await client.get(f"/v1/runs/{run_id}")).json()["status"] == "review_required"
            raise RuntimeError("that process died")

    assert (await client.post(f"/v1/runs/{run_id}/review", json=review)).status_code == 200
    (decided,) = await app.state.run_store.reviews(run_id)
    assert (decided.decision, decided.reviewer) == ("approve", "local")


@pytest.mark.anyio
async def test_a_failed_resume_leaves_the_run_waiting_and_forgets_its_decisions(
    client, monkeypatch
):
    use_diagnosed_run()
    run_id = await start(client)
    monkeypatch.setattr(app.state.runs, "_context", None)  # the resume now fails inside the graph

    review = {"decisions": {"c0": "approve"}}
    assert (await client.post(f"/v1/runs/{run_id}/review", json=review)).status_code == 502
    assert await app.state.run_store.reviews(run_id) == []
    assert (await listed(client))[0]["status"] == "review_required"


@pytest.mark.anyio
async def test_a_run_that_waits_for_review_but_was_never_recorded_can_still_be_reviewed(client):
    use_diagnosed_run()
    run_id = await start(client)
    use_diagnosed_run()  # a new, empty run store: as for a run from before the runs table

    review = {"decisions": {"c0": "reject"}}
    assert (await client.post(f"/v1/runs/{run_id}/review", json=review)).status_code == 200
    (run,) = await listed(client)
    assert (run["run_id"], run["status"], run["started_by"]) == (run_id, "completed", None)


@pytest.mark.anyio
async def test_a_failed_run_is_recorded_and_reported_as_failed(client):
    use_runs(ExplodingTraces())
    run_id = await start(client)

    assert (await listed(client))[0]["status"] == "failed"
    status = await client.get(f"/v1/runs/{run_id}")
    assert status.status_code == 200 and status.json()["status"] == "failed"
    assert PHI not in status.text


@pytest.mark.anyio
async def test_a_run_whose_trace_session_cannot_open_is_recorded_as_failed(client):
    use_runs(open_traces=broken_session)
    assert (await post_stream(client)).status_code == 502
    (run,) = await listed(client)
    assert run["status"] == "failed" and run["ended_at"] is not None
    # It never reached a checkpoint, so its status comes from the record alone.
    status = (await client.get(f"/v1/runs/{run['run_id']}")).json()
    assert status["status"] == "failed" and status["proposals"] == []


@pytest.mark.anyio
async def test_a_run_whose_client_went_away_is_recorded_as_aborted(client):
    use_runs(two_failures(), fake_diagnoser(DIAGNOSIS))
    await run_with_a_stalled_client()
    (run,) = await listed(client)
    assert run["status"] == "aborted"
    assert (await client.get(f"/v1/runs/{run['run_id']}")).json()["status"] == "aborted"


@pytest.mark.anyio
async def test_a_user_name_longer_than_the_column_is_422(client):
    response = await client.post(
        "/v1/runs/stream",
        json={"target_app": "medas"},
        headers={"X-User-Name": "x" * (NAME_MAX + 1)},
    )
    assert response.status_code == 422
    assert await listed(client) == []


@pytest.mark.anyio
async def test_the_app_refuses_to_start_with_dry_run_off(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)  # refused before the database is needed
    with pytest.raises(NotImplementedError):
        async with app.router.lifespan_context(app):
            pass
