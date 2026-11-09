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
| `backend/agent/` | The graph: `graph.py` (`build_graph(checkpointer=None, store=None)`: placeholder nodes except `collect_traces` and `cluster_failures`, early-exit conditional edges; invoke with `ainvoke(..., config, context=TraceContext(client, embedder))` inside an open `TraceClient`; `config` needs a `thread_id` when there is a checkpointer), `context.py` (`TraceContext`, the per-invoke runtime context holding the trace client and the required `embedder`, and the `TraceSearch` protocol), `nodes/collect_traces.py` (real `collect_traces`, reads the client from `runtime.context`), `nodes/cluster_failures.py` (real `cluster_failures`, runs the clustering off the event loop and writes `clusters` and `unclustered`), `clustering.py` (pure `cluster_summaries(summaries, embedder)`; the README's clustering section explains the two stages), `embeddings.py` (`Embedder` protocol and the local `FastEmbedEmbedder`; the offline `HashingEmbedder` test double is in `tests/fakes.py`), `const.py` (clustering thresholds, tuned on the synthetic fixture with the real model), `state.py` (`TriageState`, with optional `since`/`until` window and `unclustered`, and the `Cluster` contract: `cluster_id`, `trace_ids`, `signature`, `exemplar_trace_ids`, `method` of `hdbscan` or `step_error`), `mcp_client.py` (`TraceClient`: async context manager holding one stdio session to the trace server for a graph run, typed `search_failed_traces`; LangChain `tools()` come with the diagnoser). May import only `trace_store.models` from the server side |
| `backend/trace_store/` | Server side of trace access: `models.py` (`TraceSummary`, `SpanNode`, `FailedTraceQuery` contracts, and the `TraceId` argument type), `const.py`, `reader.py` (`TraceReader` protocol, `FixtureTraceReader`), `mcp_server.py` (read-only FastMCP server; run with `uv run python -m trace_store.mcp_server`), `guard.py` (`TraceGuard`, the per-call budget and audit-log middleware), `fixtures/medas_traces.json` (synthetic traces) |
| `backend/main.py` | FastAPI app: `GET /health` and the runs router; the future home of the trace collector (`POST /v1/traces`). Its lifespan opens an `AsyncPostgresSaver` from `DATABASE_URL` (required; `setup()` creates the tables) and compiles the graph with it into `app.state.graph`; the store is still `InMemoryStore`. The Postgres wiring stays out of `agent/` (`test_boundaries.py` forbids the Postgres saver and store imports there). Use a role separate from the read-only trace role |
| `backend/api/runs.py` | `POST /v1/runs` (`target_app`, optional `since`/`until`): opens a `TraceClient`, runs the graph from `app.state.graph` once on a fresh `thread_id` (returned as `run_id`) and returns counts (including `unclustered`) plus `actions_log`, never raw state (it can hold clinical span data); checkpoints do hold state, so keep it to ids and signatures. Synchronous for now; becomes `202` plus a status and review endpoint once `interrupt()` lands. API tests set `app.state.graph` and `app.state.embedder` (a `HashingEmbedder`, so tests never download the model) in the `client` fixture because `ASGITransport` skips the lifespan. Tests patch `TraceClient` with `monkeypatch`; shared fakes are in `tests/fakes.py` |
| `backend/pyproject.toml`, `backend/uv.lock` | uv project (dependencies include `fastapi`, `langgraph`, `fastmcp`, `langchain-mcp-adapters`, `uvicorn`); add packages with `uv add`, never `pip`. `fastmcp` is pinned `<4` because `langchain-mcp-adapters` requires `mcp<2` and FastMCP 4 needs `mcp` 2 (the adapters fail to import against it); lift the pin once the adapters support `mcp` 2 |
| `backend/.venv` | Virtualenv for the backend (gitignored) |
| `pyrightconfig.json` | Points Pylance/Pyright at `backend/.venv` so imports resolve when the editor opens the repo root |
| `frontend/` | Next.js 16 (App Router, TypeScript, Tailwind 4, Biome, React Compiler, npm, shadcn/ui on Base UI): one page, `app/page.tsx` with the client component `app/_components/run-panel.tsx` (form, then idle/running/success/empty/error result states, Cancel via `AbortController`). `lib/api.ts` is the only code that knows the backend URL (`runTriage`, `checkHealth`, `RunError`); `lib/types.ts` mirrors `RunRequest`/`RunResponse` by hand. `next.config.ts` rewrites `/api/:path*` to `${BACKEND_URL:-http://localhost:8000}/v1/:path*` (and `/api/health` to `/health`) because the backend has no CORS. shadcn primitives are in `components/ui/` (add more with `npx shadcn@latest add <name>`); the future trace viewer and review UI go here too. Read `frontend/AGENTS.md` before frontend work: this Next.js version differs from older docs, and its guides live in `frontend/node_modules/next/dist/docs/` |
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

`RUN_SLOW=1 uv run pytest -k fastembed` repeats the clustering check with the real embedding model; setup, cache location and offline use are in the README. Without `RUN_SLOW` that test is skipped, so CI never downloads the model.

`uv run ruff check --fix .` and `uv run ruff format .` fix what they report. Ruff is configured in `backend/pyproject.toml` (rules `E,F,I,UP,B`, line length 100).

Planned: a ruff pre-commit hook, `langgraph dev` for Studio (compile without a local checkpointer/store and point `langgraph.json` at the module's `graph`).

## Conventions

- Python, Pydantic models for all structured output and state. Store plain dicts in state, or register the models module with the checkpoint serializer, to avoid the LangGraph serialization warning.
- Target layout: `backend/agent/` (graph, `mcp_client.py`, later `nodes/` and `evals/`) and `backend/trace_store/` (contracts, reader, MCP server, later the Postgres reader); run modules from `backend/`, e.g. `uv run python -m agent.graph`. Do not name a package `mcp/`: it would shadow the official `mcp` package that FastMCP imports; Next.js UI in `frontend/` (PLAN.md still says `ui/`).
- Failure categories: `retrieval_miss`, `tool_schema_error`, `context_overflow`, `prompt_regression`, `model_quality`, `infra_error`, plus MAST top-level `system_design`, `inter_agent_misalignment`, `task_verification`, and `unknown`.
- Frontend design system lives in `frontend/app/globals.css` (see the comment block there): dark navy surfaces with one electric blue accent (`primary`), `success`/`destructive` for status only. Four type sizes via `type-h1` (24), `type-h2` (16), `type-h3` (14), `type-h4` (12 mono overline) plus `type-body` (14), and two weights (400, 500); do not use `text-xs`/`text-lg`/`text-3xl` or `font-semibold`. Desktop layout is a 12-column grid with body content on 9 columns (3/4).
- Eval = fault injection in Medas (6 seeded faults, varied inputs, healthy controls). Grade on the injected cause, not just the visible symptom.
- For parallel subagent work: contracts and fixtures first, one owner per path, stubs for neighbouring features. See `.claude/prds/tracescan.work-packages.md`.
