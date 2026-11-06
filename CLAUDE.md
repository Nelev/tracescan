# TraceScan

Multi-agent LLM failure triage (AI Engineering capstone). It reads an LLM app's traces, clusters the failures, diagnoses each cluster, and drafts GitHub issues plus regression tests for a human to approve. First target app: Medas, a clinician-facing RAG assistant.

## Project state

Planning stage. Monorepo with `backend/` (Python, FastAPI) and `frontend/` (Next.js, default starter page only), same layout as the `coa-agent` project. The code lives in two backend packages: `backend/agent/` (the graph) and `backend/trace_store/` (trace contracts, reader and MCP server). There is no `tracescan/` package. What exists:

| Path | What it is |
| --- | --- |
| `PLAN.md` | Source of truth for scope, architecture, task order and "Done when" checks |
| `.claude/prds/tracescan.prd.md` | PRD: problem, metrics, scope, open questions |
| `.claude/prds/tracescan.work-packages.md` | Features and cards split for parallel subagents. Generated; do not hand-edit |
| `backend/tracedoctor_graph.py` | LangGraph sketch with stubbed nodes; the starting point for the real graph |
| `backend/agent/` | The graph: `graph.py` (`build_graph()`: placeholder nodes except `collect_traces`, early-exit conditional edges; invoke with `ainvoke(..., context=TraceContext(client))` inside an open `TraceClient`), `context.py` (`TraceContext`, the per-invoke runtime context, and the `TraceSearch` protocol), `nodes/collect_traces.py` (real `collect_traces`, reads the client from `runtime.context`), `state.py` (`TriageState`, with optional `since`/`until` window), `mcp_client.py` (`TraceClient`: async context manager holding one stdio session to the trace server for a graph run, typed `search_failed_traces`; LangChain `tools()` come with the diagnoser). May import only `trace_store.models` from the server side |
| `backend/trace_store/` | Server side of trace access: `models.py` (`TraceSummary`, `SpanNode`, `FailedTraceQuery` contracts), `const.py`, `reader.py` (`TraceReader` protocol, `FixtureTraceReader`), `mcp_server.py` (read-only FastMCP server; run with `uv run python -m trace_store.mcp_server`), `fixtures/medas_traces.json` (synthetic traces) |
| `backend/main.py` | FastAPI app: `GET /health` and the runs router; the future home of the trace collector (`POST /v1/traces`) |
| `backend/api/runs.py` | `POST /v1/runs` (`target_app`, optional `since`/`until`): opens a `TraceClient`, runs the compiled graph once and returns counts plus `actions_log`, never raw state (it can hold clinical span data). Synchronous for now; becomes `202` plus a status and review endpoint once `interrupt()` and a checkpointer land. Tests patch `TraceClient` with `monkeypatch`; shared fakes are in `tests/fakes.py` |
| `backend/pyproject.toml`, `backend/uv.lock` | uv project (dependencies include `fastapi`, `langgraph`, `fastmcp`, `langchain-mcp-adapters`, `uvicorn`); add packages with `uv add`, never `pip`. `fastmcp` is pinned `<4` because `langchain-mcp-adapters` requires `mcp<2` and FastMCP 4 needs `mcp` 2 (the adapters fail to import against it); lift the pin once the adapters support `mcp` 2 |
| `backend/.venv` | Virtualenv for the backend (gitignored) |
| `pyrightconfig.json` | Points Pylance/Pyright at `backend/.venv` so imports resolve when the editor opens the repo root |
| `frontend/` | Next.js 16 (App Router, TypeScript, Tailwind 4, Biome, React Compiler, npm) scaffolded with the `create-next-app` starter page; the future trace viewer and review UI. Read `frontend/AGENTS.md` before frontend work: this Next.js version differs from older docs, and its guides live in `frontend/node_modules/next/dist/docs/` |
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

Run the graph sketch (needs `langgraph` 1.x, which `pyproject.toml` does not list yet; add it with `uv add langgraph`):

```bash
cd backend && uv run python tracedoctor_graph.py
```

It runs to the review pause, prints proposals, then resumes with decisions on the same `thread_id`.

Frontend commands run from `frontend/` (install with `npm install`):

```bash
cd frontend && npm run dev
```

`npm run build` builds, `npm run lint` runs Biome, and `npx tsc --noEmit` typechecks. There is no test runner yet.

Regenerate the board and work-packages brief after editing `tools/board/*.js` (from the repo root):

```bash
node tools/board/build-board.js tracescan-board.html .claude/prds/tracescan.work-packages.md
```

Backend checks (run from `backend/`; the Backend CI workflow runs the first three):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
```

`uv run ruff check --fix .` and `uv run ruff format .` fix what they report. Ruff is configured in `backend/pyproject.toml` (rules `E,F,I,UP,B`, line length 100).

Planned: a ruff pre-commit hook, `langgraph dev` for Studio (compile without a local checkpointer/store and point `langgraph.json` at the module's `graph`).

## Conventions

- Python, Pydantic models for all structured output and state. Store plain dicts in state, or register the models module with the checkpoint serializer, to avoid the LangGraph serialization warning.
- Target layout: `backend/agent/` (graph, `mcp_client.py`, later `nodes/` and `evals/`) and `backend/trace_store/` (contracts, reader, MCP server, later the Postgres reader); run modules from `backend/`, e.g. `uv run python -m agent.graph`. Do not name a package `mcp/`: it would shadow the official `mcp` package that FastMCP imports; Next.js UI in `frontend/` (PLAN.md still says `ui/`).
- Failure categories: `retrieval_miss`, `tool_schema_error`, `context_overflow`, `prompt_regression`, `model_quality`, `infra_error`, plus MAST top-level `system_design`, `inter_agent_misalignment`, `task_verification`, and `unknown`.
- Eval = fault injection in Medas (6 seeded faults, varied inputs, healthy controls). Grade on the injected cause, not just the visible symptom.
- For parallel subagent work: contracts and fixtures first, one owner per path, stubs for neighbouring features. See `.claude/prds/tracescan.work-packages.md`.
