# TraceScan

A multi-agent system that acts as an on-call engineer for an LLM application. It reads the app's traces, groups the failures, diagnoses why each group happened, states how far each diagnosis has been verified, and drafts a GitHub issue plus a regression test for a human to approve.

Built as the AI Engineering capstone. The first target app is **Medas**, a clinician-facing RAG assistant.

> **Status: planning stage.** The repo holds the plan, a LangGraph sketch with stubbed nodes, a minimal FastAPI app and the Next.js starter. The collector, trace store, real nodes and eval do not exist yet. `PLAN.md` is the source of truth for scope and task order.

## The problem

Observability tools show what happened in each run, but someone still has to scroll through hundreds of failed traces to find the pattern. TraceScan turns that into a short report, for example: "38 failures this week fall into 3 groups; group A is the retriever returning nothing for drug-interaction questions; here are the cited spans, a draft issue and a test case."

## Scope

TraceScan runs a fixed triage pipeline, not an open chat: collect failures, cluster them, diagnose each cluster, check against known issues, then propose actions that a human approves.

What sets it apart from chat-with-your-traces tools:

- **Batch triage**: works across all failures in a time window and groups them.
- **Taxonomy-based diagnosis**: each cluster gets one category from a fixed list, with the trace spans cited as evidence.
- **Verification status**: every proposal says how far it was checked. In the MVP all diagnoses are `unverified`; nothing is dropped because it did not reproduce.
- **Memory of known issues**: repeat failures update an existing issue instead of creating a duplicate.
- **Closing the loop**: every approved issue comes with a regression case for the eval dataset.
- **Own tracing stack**: no third-party observability platform. Medas is instrumented with OpenTelemetry (`gen_ai.*` attributes) and sends traces to a FastAPI OTLP collector, which stores them in Postgres.

Failure categories: `retrieval_miss`, `tool_schema_error`, `context_overflow`, `prompt_regression`, `model_quality`, `infra_error`, the three top-level [MAST](https://arxiv.org/abs/2503.13657) categories (`system_design`, `inter_agent_misalignment`, `task_verification`), and `unknown`.

### MVP (due day 10 of 16)

- Medas traced into the own trace store, plus a traffic generator
- Minimal collector, Postgres store, heuristic scoring and a read-only MCP server
- Clustering (embeddings + HDBSCAN), diagnoser with structured output, human review gate
- Dry-run actions: issues written to `out/issues/<cluster>.md`, regression cases to a local JSONL file
- Fault-injection eval with six seeded Medas faults and healthy controls
- Minimal trace viewer in Next.js

### Stretch

Replay-based reproducer, known-issues memory with semantic matching, real GitHub issue creation, MAST-Data agreement study, review dashboard, LLM-judge scoring.

### Out of scope

Any change made without human approval, and automatically fixing the bugs found (TraceScan files issues, it does not patch code).

## The LangGraph graph

One `StateGraph` with nine nodes, two parallel fan-outs (via `Send`) and one pause for human approval.

```mermaid
flowchart TD
    START([START]) --> collect_traces
    collect_traces --> cluster_failures
    cluster_failures -- "no clusters" --> END1([END])
    cluster_failures -- "Send per cluster" --> diagnose_cluster
    diagnose_cluster -- "x N, parallel" --> join_diagnoses
    join_diagnoses -- "Send per diagnosis" --> reproduce_failure
    reproduce_failure -- "x N, parallel" --> match_known_issues
    match_known_issues --> draft_proposals
    draft_proposals --> human_review
    human_review -- "nothing approved" --> END2([END])
    human_review -- "some approved" --> apply_actions
    apply_actions --> END3([END])
```

| Node | What it does | Touches the outside world? |
| --- | --- | --- |
| `collect_traces` | Pulls failed or low-score traces for the time window through the read-only MCP server | Read |
| `cluster_failures` | Groups failures with embeddings + HDBSCAN. Code only, no LLM calls | No |
| `diagnose_cluster` ×N | One agent per cluster (LangChain `create_agent`, `response_format=Diagnosis`, recursion limit ~12) that can inspect span trees through read-only tools | Read |
| `join_diagnoses` | No-op barrier that waits for every diagnosis | No |
| `reproduce_failure` ×N | Stretch: replays exemplar inputs in a sandbox. In the MVP it only marks the diagnosis `unverified` | Execute (stretch) |
| `match_known_issues` | Links clusters to issues from earlier runs via the long-term store | Read |
| `draft_proposals` | Builds a create-or-update issue proposal and a regression case per cluster | No |
| `human_review` | `interrupt()` with the proposals; resumes with approve or reject per cluster | No |
| `apply_actions` | Writes approved proposals only: GitHub, eval dataset, known-issues store. `dry_run` defaults to `True` | Write |

### Clustering and the local embedding pipeline

`cluster_failures` is plain code: no LLM calls, and no failure text leaves the machine.

```text
failed traces (TraceSummary)
  -> text per failure:  "<failing step>: <error message> | <signature>"
  -> local embedding model (fastembed, ONNX, CPU): one 384-number vector per failure
  -> HDBSCAN: dense groups, plus noise (min_cluster_size=3, min_samples=4)
  -> noise regrouped by failing step and normalised error; a group of 3 or more becomes a cluster
  -> clusters + unclustered
```

- **Text.** Built only from fields already on `TraceSummary`: failing step, error message and signature. No raw span attributes, and scores and timings are left out so they do not pull unrelated failures together. Digits in the error and signature are masked as `#`, so values that differ between traces do not split one cause.
- **Embedding.** `BAAI/bge-small-en-v1.5` run through [fastembed](https://github.com/qdrant/fastembed) (ONNX Runtime on the CPU, about 65MB). Similar failures get nearby vectors. The model loads on first use, and the API process shares one instance. Embedding is synchronous and CPU-bound, so the node runs it with `asyncio.to_thread`.
- **HDBSCAN.** Finds dense groups without being told how many there are, and labels failures that fit no group as noise. The thresholds were tuned on the synthetic fixture with the real model; what was tried and why is in `backend/agent/const.py`.
- **Second stage.** HDBSCAN cannot see a single dense group (it labels the whole group noise), and one fault often causes most of a run's failures. So the noise is regrouped by failing step and error type (digits and quoted values masked), and a group of 3 or more becomes a cluster.
- **Small runs.** With fewer than 6 failed traces, embedding is skipped: failures are grouped by step and error type and every group is a cluster, since nothing can be called noise from so little data. The model is not even loaded.
- **Output.** `clusters` is a list of `Cluster` dicts: `cluster_id` (`c0`, `c1`, … by size, stable for the same input), `trace_ids`, `signature`, `exemplar_trace_ids` (the 3 newest traces) and `method` (`hdbscan` or `step_error`). `unclustered` holds the trace ids that fit no cluster. They are kept and counted in the API response, but not diagnosed in the MVP.

### State

One shared `TriageState` flows through the graph. Fields filled by parallel branches (`diagnoses`, `reproductions`, `actions_log`) use an append reducer (`Annotated[list[...], operator.add]`), so results merge instead of overwriting. Parallel branches get small private inputs (`ClusterTask`, `ReproTask`), not the whole state, which keeps prompts short.

Key models: `TraceSummary`, `Diagnosis` (category, root cause, suggested fix, confidence, cited `Evidence`), `Reproduction` and `IssueProposal` are Pydantic. `Cluster` is a `TypedDict` in `backend/agent/state.py`, because state holds plain dicts.

### Memory

| Kind | Component | Scope | Holds |
| --- | --- | --- | --- |
| Short-term | Checkpointer (`AsyncPostgresSaver`, opened in the API lifespan from `DATABASE_URL`) | One run, keyed by `thread_id` (a fresh id per run, returned as `run_id`) | Graph state at every step, so a run can pause at review and resume later |
| Long-term | Store (`InMemoryStore`, later `PostgresStore`) | All runs, namespaced by target app | Known issues: cluster signature → issue id |

The store is written only after an approved action, so rejected proposals never become "known".

Checkpoints hold graph state in Postgres, so state stays at trace ids and signatures, never raw span attributes. Give `DATABASE_URL` a role that is separate from the read-only trace role.

### Safety invariants

- Trace access is read-only. The MCP server (`search_failed_traces`, `get_trace_tree`, `get_span`) connects with a read-only Postgres role; the agent never touches the database directly.
- All writes happen only in `apply_actions`, only for human-approved proposals.
- `dry_run` is on by default. A dry run writes local files and nothing else.
- Every diagnosis must cite real trace ids and spans from its cluster.
- Medas traces may contain clinical content; raw span attributes must be checked for personal data before they reach issues, fixtures or logs.

### Sketch vs. target

`backend/tracedoctor_graph.py` is the starting point and runs end to end with fake data. It differs from the target design in a few places:

- Nodes are stubs; `diagnose_cluster` is a plain function, not yet an agent.
- It still mentions Langfuse in comments (stale: the project builds its own tracing stack).
- `draft_proposals` skips clusters that did not reproduce. The MVP rule is the opposite: keep every cluster and mark it `unverified`.

## Evaluation

Faults are injected into Medas one at a time, each triggered by several input sets, with healthy runs as controls (TraceScan should propose nothing there):

1. Retriever returns zero chunks for one question category
2. A tool's input schema no longer matches what the model sends
3. System prompt truncated so a key instruction is lost
4. Context window too small for long documents
5. Model swapped for a weaker one
6. Upstream API timeout on a share of calls

Diagnoses are graded on the injected cause, not just the visible symptom. Metrics: detection rate, root-cause accuracy, false positives, duplicate rate on a second run, false alarms on healthy runs, and cost and time per run.

## Repository layout

| Path | What it is |
| --- | --- |
| `PLAN.md` | Scope, architecture, task order and "Done when" checks |
| `.claude/prds/` | PRD and the generated work-packages brief |
| `backend/` | Python (FastAPI + LangGraph); `main.py` opens the Postgres checkpointer and is the future trace collector, `api/runs.py` is `POST /v1/runs`, `tracedoctor_graph.py` the graph sketch |
| `frontend/` | Next.js 16 app: a run console today, the trace viewer and review UI later |
| `tools/board/`, `tracescan-board.html` | Kanban board generator and its output |
| `CLAUDE.md` | Working rules and commands for Claude Code |

## Running it

Python is managed with [uv](https://docs.astral.sh/uv/); do not use `pip`.

```bash
cd backend && uv sync
```

The API checkpoints each run into Postgres. Start one (this is a throwaway database; any Postgres works):

```bash
docker run -d --name tracescan-db -e POSTGRES_PASSWORD=tracescan -p 127.0.0.1:5433:5432 pgvector/pgvector:pg17
```

Run the API (docs at `/docs`). It fails at startup without `DATABASE_URL` and creates the checkpoint tables on first start:

```bash
cd backend && DATABASE_URL=postgresql://postgres:tracescan@127.0.0.1:5433/postgres uv run uvicorn main:app --reload
```

`POST /v1/runs` with `{"target_app": "medas"}` runs the graph once and returns counts (failed traces, clusters, unclustered failures, diagnoses, proposals), the actions log and a `run_id`, which is the run's `thread_id`.

Run the backend tests. Set `TEST_DATABASE_URL` to a Postgres as well to run the persistence test (see the top of `backend/tests/test_persistence.py`):

```bash
cd backend && uv run pytest
```

Run the graph sketch:

```bash
cd backend && uv run python tracedoctor_graph.py
```

It runs to the review pause, prints the proposals, then resumes with decisions on the same `thread_id`.

Run the frontend:

```bash
cd frontend && npm install && npm run dev
```

### Running the local embedding model

There is no server to start and no API key. `uv sync` installs the runtime (`fastembed`, ONNX Runtime and scikit-learn; no PyTorch, no GPU). The model weights are not in the repo: the first time the model is needed, fastembed downloads `BAAI/bge-small-en-v1.5` (ONNX, about 65MB) from Hugging Face and caches it. After that it runs inside the Python process, on the CPU.

Small runs never load it (see above), and neither does any normal test: tests use `HashingEmbedder` from `backend/tests/fakes.py`, an offline stand-in, so CI never downloads anything. Only the opt-in test below needs it.

Check that it works. This prints `(1, 384)`, one vector of 384 numbers:

```bash
cd backend && uv run python -c "from agent.embeddings import FastEmbedEmbedder; print(FastEmbedEmbedder().embed(['retrieve returned 0 chunks']).shape)"
```

Run the clustering check with the real model against the synthetic fixture (four known groups plus two outliers). It is skipped unless `RUN_SLOW` is set:

```bash
cd backend && RUN_SLOW=1 uv run pytest -k fastembed
```

**Where the model is cached.** In `FASTEMBED_CACHE_PATH` if set, otherwise in a `fastembed_cache` folder in the system temp dir (usually `/tmp/fastembed_cache`). Temp dirs are normally cleared on reboot, which means a new download, so point it somewhere persistent:

```bash
export FASTEMBED_CACHE_PATH=$HOME/.cache/fastembed
```

**Offline use.** Once the model is cached it loads with the network switched off; set `HF_HUB_OFFLINE=1` to stop any contact with Hugging Face. With an empty cache and no network it fails with `Could not load model ... from any source`. For a container, download the model once and bake the cache folder into the image, or mount it.

**How the model is downloaded and run.** Our code never downloads or runs the model itself. It makes one call, and fastembed (0.9.1) does the rest. This is all of it, in `backend/agent/embeddings.py`:

```python
self._model = TextEmbedding(EMBEDDING_MODEL)  # first use: download if not cached, then load
np.asarray(list(self._model.embed(texts)), dtype=np.float32)  # inference
```

1. **Startup.** The API lifespan in `main.py` creates one `FastEmbedEmbedder()`. That only builds a wrapper, so nothing is downloaded at startup.
2. **First use.** `cluster_failures` calls `cluster_summaries` through `asyncio.to_thread`. With 6 or more failures, `embed()` calls `_load()`, which creates the `TextEmbedding` under a lock, so concurrent runs load it once.
3. **Download.** fastembed maps `BAAI/bge-small-en-v1.5` to the Hugging Face repo `Qdrant/bge-small-en-v1.5-onnx-Q` (an ONNX build of the model, `model_optimized.onnx`, plus its tokenizer, about 67MB) and fetches it with Hugging Face's `snapshot_download` into the cache folder. Files that are already cached are checked and reused without the network.
4. **Inference.** The `tokenizers` library splits each text into tokens, and an ONNX Runtime session on the CPU runs the network. fastembed keeps only the first token's vector (the `[CLS]` token) and scales it to length 1, giving one 384-number vector per text. HDBSCAN then uses cosine distance on those vectors.
