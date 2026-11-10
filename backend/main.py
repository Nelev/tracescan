import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.memory import InMemoryStore

from agent.embeddings import FastEmbedEmbedder
from agent.graph import build_graph
from agent.mcp_client import TraceClient
from agent.model import build_diagnoser_model, build_ui_spec_model
from api.runs import router as runs_router
from runs import Runs


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # DATABASE_URL: a role separate from the read-only trace role.
    async with AsyncPostgresSaver.from_conn_string(os.environ["DATABASE_URL"]) as checkpointer:
        await checkpointer.setup()  # creates the checkpoint tables when missing
        app.state.graph = build_graph(checkpointer, InMemoryStore())
        # One embedder per process (it loads its model on first use); the diagnoser's chat model
        # needs OPENROUTER_API_KEY, like DATABASE_URL. Each run opens its own trace session.
        app.state.runs = Runs(
            app.state.graph, FastEmbedEmbedder(), build_diagnoser_model(), TraceClient
        )
        # The small model that writes the UI spec of each streamed message (api.ui_spec).
        app.state.ui_spec_model = build_ui_spec_model()
        yield


app = FastAPI(title="TraceScan", lifespan=lifespan)
app.include_router(runs_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
