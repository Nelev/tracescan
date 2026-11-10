"""The eval runner: one seeded day of traces through the triage graph, saved as a results file.

Run from backend/:  uv run --env-file .env python -m eval.run [--end 2026-01-29T12:00:00Z]

It seeds the day (scripts/seed_traces.py), runs the graph on that day's window, and writes what
the graph found, with the answer key next to it, to out/eval/. The graph has no checkpointer
here, so the invoke returns at the review pause with the whole state: nothing is reviewed,
apply_actions never runs, and the results file is the only thing written.

Needs DATABASE_URL (the seed writes spans), TRACE_DATABASE_URL (the trace server reads them;
the same database) and OPENROUTER_API_KEY. One run is one diagnoser call per cluster.
"""

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.language_models import BaseChatModel

from agent.context import TraceAccess, TraceContext
from agent.embeddings import Embedder, FastEmbedEmbedder
from agent.graph import build_graph
from agent.mcp_client import TraceClient
from agent.model import build_diagnoser_model
from agent.state import TriageState
from api.traces import decode
from eval.metrics import OUT_DIR
from scripts.seed_traces import APP, DAY, export, kinds, seed

# A fixed day, so every run grades the same traces, and one no other seeded day overlaps.
# Change it when the seeded cases change: a day already stored keeps its old traces, and a
# trace the answer key does not know stops the scoring.
DEFAULT_END = datetime(2026, 1, 29, 12, tzinfo=UTC)


async def triage(
    end: datetime, traces: TraceAccess, embedder: Embedder, model: BaseChatModel
) -> dict[str, Any]:
    """Run the graph on the day that ends at `end`; what it found, next to the answer key."""
    state = TriageState(target_app=APP, since=(end - DAY).isoformat(), until=end.isoformat())
    started = time.perf_counter()
    found = await build_graph().ainvoke(state, context=TraceContext(traces, embedder, model))
    return {
        "end": end.isoformat(),
        "seconds": round(time.perf_counter() - started, 1),
        "kinds": kinds(end),  # the answer key: trace id to seeded kind (eval/ground_truth.py)
        # The failed traces the graph collected, and the span each failed in (ids only).
        "failing_spans": {
            trace["trace_id"]: trace["failing_span_id"] for trace in found.get("failed_traces", [])
        },
        "clusters": found.get("clusters", []),
        "unclustered": found.get("unclustered", []),
        "diagnoses": found.get("diagnoses", []),
        "diagnosis_failures": found.get("diagnosis_failures", []),
        "model_usage": found.get("model_usage", []),
    }


async def run(end: datetime, database_url: str, trace_database_url: str) -> dict[str, Any]:
    await seed(database_url, decode(export(end)))
    async with TraceClient(trace_database_url) as traces:
        model = build_diagnoser_model()
        return {"model": getattr(model, "model_name", "unknown")} | await triage(
            end, traces, FastEmbedEmbedder(), model
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--end",
        type=datetime.fromisoformat,
        default=DEFAULT_END,
        help=f"when the seeded day ends, with an offset (default: {DEFAULT_END.isoformat()})",
    )
    end = parser.parse_args().end
    if end.tzinfo is None:
        parser.error("--end needs an offset, for example 2026-01-29T12:00:00Z")
    database_url = os.environ.get("DATABASE_URL")
    trace_database_url = os.environ.get("TRACE_DATABASE_URL")
    if not database_url or not trace_database_url:
        parser.error("set DATABASE_URL and TRACE_DATABASE_URL (the same database)")

    result = asyncio.run(run(end, database_url, trace_database_url))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(result, indent=2))
    print(
        f"{len(result['failing_spans'])} failed traces, {len(result['clusters'])} clusters, "
        f"{len(result['diagnoses'])} diagnoses in {result['seconds']}s: {path}"
    )


if __name__ == "__main__":
    main()
