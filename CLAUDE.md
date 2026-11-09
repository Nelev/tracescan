# TraceScan

Multi-agent LLM failure triage (AI Engineering capstone). It reads an LLM app's traces, clusters the failures, diagnoses each cluster, and drafts GitHub issues plus regression tests for a human to approve. First target app: Medas, a clinician-facing RAG assistant.

## Project state

Planning stage. Monorepo with `backend/` (Python, FastAPI) and `frontend/` (Next.js, a single run-console page), same layout as the `coa-agent` project. The code lives in two backend packages: `backend/agent/` (the graph) and `backend/trace_store/` (trace contracts, reader and MCP server). There is no `tracescan/` package. What exists:

| Path | What it is |
| --- | --- |
| `PLAN.md` | Source of truth for scope, architecture, task order and "Done when" checks |
| `.claude/prds/tracescan.prd.md` | PRD: problem, metrics, scope, open questions |
| `.claude/prds/tracescan.work-packages.md` | Features and cards split for parallel subagents. Generated; do not hand-edit |
| `backend/tracedoctor_graph.py` | LangGraph sketch with stubbed nodes; the starting point for the real graph |
| `backend/agent/` | The graph: `graph.py` (`build_graph(checkpointer=None, store=None)`: placeholder nodes except `collect_traces`, `cluster_failures` and `diagnose_cluster`, early-exit conditional edges, and `route_after_cluster` fanning out one `Send` per cluster; invoke with `ainvoke(..., config, context=TraceContext(client, embedder))` inside an open `TraceClient`; `config` needs a `thread_id` when there is a checkpointer), `context.py` (`TraceContext`, the per-invoke runtime context holding the trace client and the required `embedder` and chat `model`, and the `TraceAccess` protocol: `search_failed_traces` and `get_trace_tree`), `model.py` (`build_diagnoser_model()`, the OpenRouter chat model named by `DIAGNOSER_MODEL`), `progress.py` (`ProgressTransformer`, registered in `compile(transformers=[...])`: with `astream_events(..., version="v3")` it turns the raw `tasks` channel into allowlisted progress events (node, task id, cluster id, ok, counts; never `input`, `result` or `error`). The raw stream carries full state and so possibly clinical data; consume it only through `progress_events(stream)`, never by iterating the stream. The v3 protocol is experimental and `stream.output` is a method in 1.2.20. `diagnose_cluster` copies its model with `disable_streaming=True`, because under v3 LangChain would otherwise route the call through its token-streaming path, which a plain fake model does not implement), `nodes/collect_traces.py` (real `collect_traces`, reads the client from `runtime.context`), `nodes/cluster_failures.py` (real `cluster_failures`, runs the clustering off the event loop and writes `clusters` and `unclustered`), `nodes/diagnose_cluster.py` (real `diagnose_cluster`: takes a `ClusterTask`, fetches the exemplar span trees, and makes one `with_structured_output(Diagnosis)` call with `taxonomy.md` as the system prompt; it overwrites `cluster_id` from the task; every cited span must be a span of the exemplar trees it was shown: if not, the model is asked once more with the valid ids listed, and if it still cites spans it was not shown they are dropped, the confidence is capped at `UNSUPPORTED_CONFIDENCE_CAP`, and with no real citation left the cluster's own first failing span is cited. The stored dict gets `evidence_check` (`valid`, `corrected` or `unsupported`, never filled by the model); a cluster that fails, including a failing retry, is logged by exception type only and its id goes to `diagnosis_failures`), `evidence.py` (the pure checks: `span_index`, `invalid_citations`, `keep_valid`, `retry_message`, `fallback_evidence`), `clustering.py` (pure `cluster_summaries(summaries, embedder)`; the README's clustering section explains the two stages), `embeddings.py` (`Embedder` protocol and the local `FastEmbedEmbedder`; the offline `HashingEmbedder` test double is in `tests/fakes.py`), `const.py` (clustering thresholds, tuned on the synthetic fixture with the real model), `state.py` (`TriageState`, with optional `since`/`until` window, `unclustered`, and the append-reducer fields `diagnoses` and `diagnosis_failures` filled by the parallel branches), `schemas.py` (data contracts: the `Cluster` TypedDict (`cluster_id`, `trace_ids`, `signature`, `exemplar_trace_ids`, `method` of `hdbscan` or `step_error`), `FailureCategory`/`FAILURE_CATEGORIES`, the `ClusterTask` input of a diagnose branch, and the `Diagnosis` and `Evidence` Pydantic models the diagnoser returns), `mcp_client.py` (`TraceClient`: async context manager holding one stdio session to the trace server for a graph run, typed `search_failed_traces` and `get_trace_tree`). May import only `trace_store.models` from the server side |
| `backend/trace_store/` | Server side of trace access: `models.py` (`TraceSummary`, `SpanNode`, `FailedTraceQuery` contracts, and the `TraceId` argument type), `const.py`, `reader.py` (`TraceReader` protocol, `FixtureTraceReader`), `mcp_server.py` (read-only FastMCP server; run with `uv run python -m trace_store.mcp_server`), `guard.py` (`TraceGuard`, the per-call budget and audit-log middleware), `fixtures/medas_traces.json` (synthetic traces) |
| `backend/main.py` | FastAPI app: `GET /health` and the runs router; the future home of the trace collector (`POST /v1/traces`). Its lifespan opens an `AsyncPostgresSaver` from `DATABASE_URL` (required; `setup()` creates the tables) and compiles the graph with it into `app.state.graph`; it also sets `app.state.embedder` and `app.state.model` (the chat model, which needs `OPENROUTER_API_KEY` at startup); the store is still `InMemoryStore`. The Postgres wiring stays out of `agent/` (`test_boundaries.py` forbids the Postgres saver and store imports there). Use a role separate from the read-only trace role |
| `backend/api/runs.py`, `backend/api/schemas.py` | `schemas.py` holds `RunRequest`/`RunResponse`. `POST /v1/runs` (`target_app`, optional `since`/`until`): opens a `TraceClient`, runs the graph from `app.state.graph` once on a fresh `thread_id` (returned as `run_id`) and returns counts (including `unclustered` and `diagnosis_failures`) plus `actions_log`, never raw state (it can hold clinical span data); checkpoints do hold state, so keep it to ids and signatures. Synchronous for now; becomes `202` plus a status and review endpoint once `interrupt()` lands. `POST /v1/runs/stream` takes the same body and streams the run as server-sent events (FastAPI's native `fastapi.sse`, no extra dependency): `run_started {run_id}`, `progress` events from `agent.progress`, then `run_completed` (the same summary) or `run_failed {}` with no detail, since the status is already 200 once the stream opens. It forwards only `progress_events(stream)`, never raw stream events. The `TraceClient` and the run stream are owned by the `_open_run` dependency, not the generator: FastAPI never closes a generator that is suspended at a `yield` when the client disconnects, but it does unwind dependencies, so the run is aborted and the trace session released at once (tested with a stalled client, without `gc.collect()`). A trace session that cannot open is a plain `502` before the stream starts; a failure after that is a `run_failed` event. API tests set `app.state.graph`, `app.state.embedder` (a `HashingEmbedder`, so tests never download the model) and `app.state.model` (a fake chat model) in the `client` fixture because `ASGITransport` skips the lifespan. Tests patch `TraceClient` with `monkeypatch`; shared fakes are in `tests/fakes.py` |
| `backend/pyproject.toml`, `backend/uv.lock` | uv project (dependencies include `fastapi`, `langgraph`, `langchain` and `langchain-openrouter` for the diagnoser, `fastmcp`, `langchain-mcp-adapters`, `uvicorn`); add packages with `uv add`, never `pip`. `fastmcp` is pinned `<4` because `langchain-mcp-adapters` requires `mcp<2` and FastMCP 4 needs `mcp` 2 (the adapters fail to import against it); lift the pin once the adapters support `mcp` 2 |
| `backend/.venv` | Virtualenv for the backend (gitignored) |
| `pyrightconfig.json` | Points Pylance/Pyright at `backend/.venv` so imports resolve when the editor opens the repo root |
| `frontend/` | Next.js 16 (App Router, TypeScript, Tailwind 4, Biome, React Compiler, npm, shadcn/ui on Base UI): one page, `app/page.tsx` with the client component `app/_components/run-panel.tsx` (the form; the date picker is loaded on demand with `next/dynamic`, about 50 KB gzipped off first load, and preloaded when Custom is hovered or focused) over `app/_components/run-console.tsx`, a console that prints each stream event as it arrives (arrival time, event name, the data exactly as received; follows the newest line, Copy and Clear). The run itself lives in the hook `app/_components/use-run-stream.ts`: one reducer holding the phase (idle/running/done/failed/lost/cancelled), the console lines (last 500) and timing, Cancel via `AbortController`. `lib/api.ts` is the only code that knows the backend URL (`openRunStream`, `RUN_STREAM_PATH`, `checkHealth`, `RunError`) and `lib/sse.ts` decodes `text/event-stream`; `lib/types.ts` mirrors `RunRequest` and the stream's event names by hand, with the two bits of event knowledge the UI needs (`runOutcome`, `isFailure`). `next.config.ts` rewrites `/api/:path*` to `${BACKEND_URL:-http://localhost:8000}/v1/:path*` (and `/api/health` to `/health`) because the backend has no CORS, and sets `compress: false`: Next's gzip buffers an event stream until the run ends (checked in `next dev` and `next start`; a `no-transform` header does not help). The UI streams from `POST /v1/runs/stream` and does not call the sync `POST /v1/runs`. Next allows one dev server per project folder, so to test next to a running one, run a copy of `frontend/` (hard-linked `node_modules`, on the same filesystem) on another port. shadcn primitives are in `components/ui/` (add more with `npx shadcn@latest add <name>`); the future trace viewer and review UI go here too. Read `frontend/AGENTS.md` before frontend work: this Next.js version differs from older docs, and its guides live in `frontend/node_modules/next/dist/docs/` |
| `tools/board/` | `build-board.js` and `card-details.js`: single source for the Kanban cards |
| `tracescan-board.html` | Generated Kanban board |

## Working rules

- Follow `PLAN.md` "Implementation plan" phase by phase. Tick a task's checkbox only when its "Done when" check passes.
- Keep the MVP tight. Do not start stretch tasks until the MVP gate (day 10) passes.
- Diagnoses are `unverified` in the MVP. Never drop a cluster because it did not reproduce.
- Cite evidence: every diagnosis must reference real trace ids and spans from its cluster.
- Medas traces may contain clinical content. Do not copy raw span attributes into issues, fixtures or logs without checking for personal data.

## Architecture (see PLAN.md for detail)

One LangGraph `StateGraph`:
`collect_traces → cluster_failures → diagnose_cluster ×N (parallel, via Send) → join_diagnoses → reproduce_failure ×N → match_known_issues → draft_proposals → human_review (interrupt) → apply_actions → END`

- `diagnose_cluster` is itself a LangChain `create_agent` with `response_format=Diagnosis` and a low recursion limit (~12). The outer pipeline stays a plain `StateGraph`.
- Parallel branches get small private inputs (`ClusterTask`, `ReproTask`), not the whole state. Fields filled by parallel branches use `Annotated[list[...], operator.add]`.
- Clustering is code (embeddings + HDBSCAN), not LLM calls. LLM calls happen per cluster, never per trace.
- Tracing stack is our own: Medas (OpenTelemetry, `gen_ai.*` attributes) → FastAPI OTLP collector → Postgres (`traces`, `spans`, `scores`) → FastMCP read-only server → graph. Decided: no third-party observability platform (no Langfuse). The Langfuse mentions in `tracedoctor_graph.py` are stale.

## Safety invariants

- Trace access is read-only: the MCP server (`search_failed_traces`, `get_trace_tree`, `get_span`) connects with a read-only Postgres role. The agent never touches the DB directly: `agent/` imports only `trace_store.models` and no DB drivers, and `backend/tests/test_boundaries.py` enforces it.
- MCP tool calls are limited where their arguments are declared and by one middleware. `search_failed_traces` serves only `ALLOWED_APPS` (checked in the tool body), and trace and span ids are typed `TraceId` (`models.py`, pattern `ID_PATTERN`), so pydantic rejects other shapes; give any new tool that takes an id the `TraceId` type. `TraceGuard` (`trace_store/guard.py`) wraps every call with a per-run budget (`MAX_TOOL_CALLS`; one server process is one graph run) and an audit log of tool, outcome and a hash of the arguments on stderr, never raw arguments, results or exception messages. Known limits: FastMCP's own "Invalid arguments for tool" warning repeats a rejected id or query on stderr, outside the guard's control; `get_trace_tree` and `get_span` take only ids, so they are not app-scoped until the Postgres reader does it.
- All writes (GitHub, eval dataset, known-issues store) happen only in `apply_actions`, only for human-approved proposals.
- `dry_run` defaults to `True`. Dry run writes `out/issues/<cluster>.md` and appends regression cases to a local JSONL file, and nothing else.
- The known-issues store is written only after an approved action, so rejected proposals never become "known".

## Commands

Backend commands run from `backend/`. This project uses `uv`, not `pip` (and `python3 -m venv` fails on this machine because `ensurepip` is missing). Create the virtualenv and install dependencies:

```bash
cd backend && uv sync
```

Run the FastAPI app (docs at `/docs`):

```bash
cd backend && uv run uvicorn main:app --reload
```

The app needs `DATABASE_URL` (for example `postgresql://user:pass@127.0.0.1:5432/tracescan`) to checkpoint run state into Postgres, and fails at startup without it. To also run the Postgres test, set `TEST_DATABASE_URL`; the docker command is at the top of `backend/tests/test_persistence.py`.

The diagnoser calls a model through OpenRouter: the app also fails at startup without `OPENROUTER_API_KEY`; optionally set `DIAGNOSER_MODEL` (an OpenRouter slug such as `anthropic/claude-sonnet-5-5`; default in `agent/const.py`). Tests never call a model. `langchain-openrouter` pulls in the `openrouter` SDK, which caps `pydantic<2.13`, so pydantic sits at 2.12 until that cap is lifted.

Run the graph sketch (needs `langgraph` 1.x, which `pyproject.toml` does not list yet; add it with `uv add langgraph`):

```bash
cd backend && uv run python tracedoctor_graph.py
```

It runs to the review pause, prints proposals, then resumes with decisions on the same `thread_id`.

Frontend commands run from `frontend/` (install with `npm install`):

```bash
cd frontend && npm run dev
```

`npm run build` builds, `npm run lint` runs Biome, and `npx tsc --noEmit` typechecks. There is no test runner yet. The UI needs the backend running too; if ports 3000 or 8000 are taken, start the backend with `--port 8010` and the frontend with `BACKEND_URL=http://localhost:8010 npm run dev -- --port 3010`.

Regenerate the board and work-packages brief after editing `tools/board/*.js` (from the repo root):

```bash
node tools/board/build-board.js tracescan-board.html .claude/prds/tracescan.work-packages.md
```

Backend checks (run from `backend/`; the Backend CI workflow runs the first three):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
```

`RUN_SLOW=1 uv run pytest -k fastembed` repeats the clustering check with the real embedding model; setup, cache location and offline use are in the README. Without `RUN_SLOW` that test is skipped, so CI never downloads the model. Likewise `RUN_LLM=1 OPENROUTER_API_KEY=... uv run pytest -k real_model` runs the diagnoser on the real model over the fixture clusters, and CI never calls a model.

`uv run ruff check --fix .` and `uv run ruff format .` fix what they report. Ruff is configured in `backend/pyproject.toml` (rules `E,F,I,UP,B`, line length 100).

Planned: a ruff pre-commit hook, `langgraph dev` for Studio (compile without a local checkpointer/store and point `langgraph.json` at the module's `graph`).

## Conventions

- Python, Pydantic models for all structured output and state. Store plain dicts in state, or register the models module with the checkpoint serializer, to avoid the LangGraph serialization warning.
- Target layout: `backend/agent/` (graph, `mcp_client.py`, later `nodes/` and `evals/`) and `backend/trace_store/` (contracts, reader, MCP server, later the Postgres reader); run modules from `backend/`, e.g. `uv run python -m agent.graph`. Do not name a package `mcp/`: it would shadow the official `mcp` package that FastMCP imports; Next.js UI in `frontend/` (PLAN.md still says `ui/`).
- Failure categories: `retrieval_miss`, `tool_schema_error`, `context_overflow`, `prompt_regression`, `model_quality`, `infra_error`, plus MAST top-level `system_design`, `inter_agent_misalignment`, `task_verification`, and `unknown`.
- Frontend design system lives in `frontend/app/globals.css` (see the comment block there): dark navy surfaces with one electric blue accent (`primary`), `success`/`destructive` for status only. Four type sizes via `type-h1` (24), `type-h2` (16), `type-h3` (14), `type-h4` (12 mono overline) plus `type-body` (14), and two weights (400, 500); do not use `text-xs`/`text-lg`/`text-3xl` or `font-semibold`. Desktop layout is a 12-column grid with body content on 9 columns (3/4).
- Eval = fault injection in Medas (6 seeded faults, varied inputs, healthy controls). Grade on the injected cause, not just the visible symptom.
- For parallel subagent work: contracts and fixtures first, one owner per path, stubs for neighbouring features. See `.claude/prds/tracescan.work-packages.md`.
