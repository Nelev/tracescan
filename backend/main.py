import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.memory import InMemoryStore

from agent.actions import require_dry_run
from agent.context import ClosedTraces, TraceContext
from agent.embeddings import FastEmbedEmbedder
from agent.graph import build_graph
from agent.mcp_client import TraceClient
from agent.model import build_diagnoser_model, build_trace_judge_model, build_ui_spec_model
from api.runs import router as runs_router
from api.trace_browser import router as trace_browser_router
from api.traces import router as traces_router
from db.engine import create_engine
from runs import PostgresRunStore, Runs
from runs.healthy import HealthyStore
from trace_store.postgres_reader import PostgresTraceReader, read_only_engine


def dry_run_setting() -> bool:
    """DRY_RUN from the environment: on unless it is set to 0, false, no or off.

    The only place the setting comes from, so no request can turn it off.
    """
    return os.environ.get("DRY_RUN", "true").strip().lower() not in {"0", "false", "no", "off"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    dry_run = dry_run_setting()
    # Checked before anything opens: better to refuse at startup than after a run's review.
    require_dry_run(dry_run)
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
        context = TraceContext(
            ClosedTraces(),
            embedder,
            build_diagnoser_model(),
            build_trace_judge_model(),
            dry_run=dry_run,
        )
        # Where each run's trace server reads spans and scores: meant for a read-only role.
        trace_database_url = os.environ["TRACE_DATABASE_URL"]
        open_traces = partial(TraceClient, trace_database_url)
        # The trace browser (api.trace_browser) reads the same store, read-only, in this process.
        trace_engine = read_only_engine(trace_database_url)
        app.state.trace_reader = PostgresTraceReader(trace_engine)
        # The judge's healthy picks, embedded with the same local model, in the same database.
        healthy = HealthyStore(engine, embedder)
        app.state.runs = Runs(app.state.graph, context, open_traces, store, healthy)
        # The small model that writes the UI spec of each streamed message (api.ui_spec).
        app.state.ui_spec_model = build_ui_spec_model()
        try:
            yield
        finally:
            await trace_engine.dispose()
            await engine.dispose()


app = FastAPI(title="TraceScan", lifespan=lifespan)
app.include_router(runs_router)
app.include_router(traces_router)
app.include_router(trace_browser_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
