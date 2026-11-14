import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import Depends, FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.memory import InMemoryStore
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from agent.context import ClosedTraces, TraceContext
from agent.embeddings import FastEmbedEmbedder
from agent.github import github_from_env
from agent.graph import build_graph
from agent.mcp_client import TraceClient
from agent.model import build_diagnoser_model, build_trace_judge_model, build_ui_spec_model
from api.rate_limit import limiter
from api.runs import router as runs_router
from api.trace_browser import router as trace_browser_router
from api.traces import CollectorTokens
from api.traces import router as traces_router
from auth import AuthSettings, session_claims
from db.engine import create_engine
from runs import PostgresRunStore, Runs
from runs.healthy import HealthyStore
from runs.known_issues import KnownIssueStore
from runs.scores import ScoreStore
from trace_store.postgres_reader import PostgresTraceReader, read_only_engine


def dry_run_setting() -> bool:
    """DRY_RUN from the environment: on unless it is set to 0, false, no or off.

    The only place the setting comes from, so no request can turn it off.
    """
    return os.environ.get("DRY_RUN", "true").strip().lower() not in {"0", "false", "no", "off"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    dry_run = dry_run_setting()
    github = github_from_env()
    # Checked before anything opens: better to refuse at startup than after a run's review.
    if not dry_run and github is None:
        raise RuntimeError("DRY_RUN is off: set GITHUB_REPO and GITHUB_TOKEN")
    if github is not None:
        await github.check()  # refuses a public repo: issues may hold clinical text
    # CLERK_SECRET_KEY is required: without it the app stops here, not on each signed-in request.
    app.state.auth = AuthSettings.from_env()
    # A collector token per allowed app is required too (COLLECTOR_TOKEN_MEDAS): the collector
    # takes spans only from an app with its token.
    app.state.collector_tokens = CollectorTokens.from_env()
    # DATABASE_URL: a role separate from the read-only trace role. One database, two owners: the
    # checkpointer creates its own tables, Alembic creates ours (runs, reviews, spans, scores).
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    app.state.engine = engine  # the collector (api.traces) writes spans through it
    async with AsyncPostgresSaver.from_conn_string(database_url) as checkpointer:
        store = PostgresRunStore(engine)
        await store.check()  # refuses to start until `alembic upgrade head` has run
        await checkpointer.setup()  # creates the checkpoint tables when missing
        app.state.graph = build_graph(checkpointer, InMemoryStore())
        # One embedder per process (it loads its model on first use); the diagnoser's and the
        # trace judge's chat models need OPENROUTER_API_KEY, like DATABASE_URL. Each run opens its
        # own trace session.
        embedder = FastEmbedEmbedder()
        # The judge's healthy picks, embedded with the same local model, in the same database:
        # Runs saves them after each run, the diagnoser reads the nearest ones.
        healthy = HealthyStore(engine, embedder)
        context = TraceContext(
            ClosedTraces(),
            embedder,
            build_diagnoser_model(),
            build_trace_judge_model(),
            healthy=healthy,
            # Decided diagnoses, saved by apply_actions after each review, read by the diagnoser.
            known_issues=KnownIssueStore(engine, embedder),
            dry_run=dry_run,
            github=github,
        )
        # Where each run's trace server reads spans and scores: meant for a read-only role.
        trace_database_url = os.environ["TRACE_DATABASE_URL"]
        open_traces = partial(TraceClient, trace_database_url)
        # The trace browser (api.trace_browser) reads the same store, read-only, in this process.
        trace_engine = read_only_engine(trace_database_url)
        app.state.trace_reader = PostgresTraceReader(trace_engine)
        # The judge's verdicts become `scores` rows, so the trace browser shows them.
        app.state.runs = Runs(
            app.state.graph, context, open_traces, store, healthy, ScoreStore(engine)
        )
        # The small model that writes the UI spec of each streamed message (api.ui_spec).
        app.state.ui_spec_model = build_ui_spec_model()
        try:
            yield
        finally:
            await trace_engine.dispose()
            await engine.dispose()


app = FastAPI(title="TraceScan", lifespan=lifespan)
# The run limit (api.rate_limit). Set here, not in the lifespan, so ASGITransport tests get it too.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]
# Every route needs a Clerk session token except these two: /health, and the collector, which
# Medas's exporter calls with its own app token instead (api.traces). tests/test_auth.py walks
# app.routes, so a route added without a session check fails it unless it is named there too. A router's dependencies
# run before its routes' own, so a request without a session never starts a run or a trace server.
app.include_router(runs_router, dependencies=[Depends(session_claims)])
app.include_router(trace_browser_router, dependencies=[Depends(session_claims)])
app.include_router(traces_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
