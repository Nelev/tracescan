# TraceScan

TraceScan triages the failures of an LLM application. It reads the app's failed traces, groups them into clusters, asks a model to diagnose each cluster with cited spans, and drafts one GitHub issue and one regression case per cluster. A person approves or rejects each draft, and only approved drafts are written.

It is the AI Engineering capstone. The first target app is **Medas**, a clinician-facing RAG assistant.

## Status

The pipeline runs end to end on synthetic traces, as a dry run.

| Part | State |
| --- | --- |
| Graph: collect, cluster, diagnose, draft, review, apply | Working |
| Graph: `reproduce_failure`, `match_known_issues` | Placeholders that return fixed values |
| Trace MCP server (read-only, sanitized, budgeted) | Working, over the Postgres reader |
| OTLP collector (`POST /v1/traces` into the `spans` table) | Working, minimal: localhost and synthetic traffic only |
| Postgres trace reader | The only trace source. A trace is failed when its lowest score is low. No read-only role yet |
| Scoring job (`trace_store/scoring.py`) | Working: five heuristic checks score each trace when its root span is stored. No model judge |
| Writes | Dry run only: local files under `backend/out/`. GitHub and eval-dataset writers do not exist, and the app refuses to start with `DRY_RUN` off |
| Run console (Next.js) | Working: start a run, watch it, list runs, review proposals |
| Eval on seeded traces (`backend/eval/`) | Working: ground truth, runner, coded scores and a judge for the root cause, on plain faults and hard cases (look-alikes, false positives, a failure with no error). It shows the diagnoses hold up and the clustering mixes look-alike failures |
| Medas instrumentation | Working, in the Medas repo (`medas-api/tracing/`): one trace per agent run, exported to the collector, with no patient text on any span. Checked with a real signed-in request |
| Fault-injection eval in Medas | Not built |

`PLAN.md` holds the scope and the task order.

## Architecture

```mermaid
flowchart LR
    medas["Medas<br/>(OpenTelemetry)"] -- "OTLP protobuf<br/>POST /v1/traces" --> collector

    subgraph backend["FastAPI backend"]
        collector["Collector<br/>api/traces.py"]
        api["Runs API + SSE<br/>api/runs.py"]
        runs["Runs module<br/>runs/"]
        agent["LangGraph graph<br/>agent/"]
        api --> runs --> agent
    end

    subgraph pg["Postgres"]
        spans[("spans")]
        app[("users, runs, reviews")]
        cp[("graph checkpoints")]
    end

    subgraph mcp["Trace MCP server (stdio subprocess, one per run)"]
        tools["3 read-only tools<br/>+ TraceGuard"]
        reader["TraceReader"]
        tools --> reader
    end

    ui["Run console<br/>Next.js"]
    llm["OpenRouter<br/>diagnoser model"]
    out[["out/issues/*.md<br/>out/regression_cases.jsonl"]]

    collector --> spans
    spans --> reader
    agent -- "TraceClient" --> tools
    agent --> llm
    agent -- "apply_actions (dry run)" --> out
    agent --> cp
    runs --> app
    ui -- "/api/* rewritten to /v1/*" --> api
```

The dotted arrow is the missing piece: the collector stores spans, but the reader that would serve them to the graph is not written.

The parts and what each one owns:

- **`backend/agent/`** is the graph. It reaches traces only through the MCP client. It imports `trace_store.models` and nothing else from the server side, and no database driver; `tests/test_boundaries.py` enforces this.
- **`backend/trace_store/`** is the server side of trace access: the contracts (`models.py`), the `TraceReader` protocol, the Postgres reader, the scoring job, the MCP server and its guard.
- **`backend/runs/`** is the only code that knows a run is a graph thread. It starts runs, reads their status from the checkpoint, and resumes them at the review. Callers never get raw graph state.
- **`backend/api/`** is HTTP and server-sent events over the runs module, plus the collector.
- **`backend/db/`** and **`backend/migrations/`** hold the application's own tables (SQLAlchemy and Alembic). LangGraph's checkpointer creates and owns its own tables in the same database.
- **`frontend/`** is one page, the run console.

## Trace structure

A trace is one request to the target app. It is a tree of spans. TraceScan uses two views of it, both defined in `backend/trace_store/models.py`.

### TraceSummary

One row per failed trace, small enough to cluster without fetching the tree:

```json
{
  "trace_id": "tr_retrieval_miss",
  "app": "medas",
  "start_time": "2026-11-05T09:00:00Z",
  "duration_ms": 2400.0,
  "status": "error",
  "error_message": "answer not grounded in retrieved context",
  "failing_span_id": "sp_rm_retrieve",
  "failing_span_name": "retrieve",
  "min_score": 0.1,
  "signature": "retrieve returned 0 relevant chunks; llm answered without sources"
}
```

A trace counts as **failed** when its lowest score is at or below `max_score` (default 0.5). An error span alone does not make it failed, since an error can be harmless (see the scoring job below). `signature` is a short text written by the producer, with no clinical content, and is what the clustering embeds.

### SpanNode

One span, with its children nested under it:

| Field | Meaning |
| --- | --- |
| `span_id`, `trace_id`, `parent_span_id` | Identity and position in the tree. The root has no parent |
| `name` | The step: `medas.request`, `retrieve`, `chat gpt-4o`, `execute_tool lookup_dosage` |
| `kind` | OpenTelemetry span kind: `server`, `client`, `internal` |
| `start_time`, `end_time` | Timezone-aware timestamps |
| `status`, `status_message` | `unset`, `ok` or `error`, and the error text |
| `attributes` | Key and value pairs, such as `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `retrieval.hits` |
| `events` | Timestamped events on the span, each with its own attributes |
| `children` | The child spans, ordered by start time |

A seeded trace whose record store is down, as a tree:

```
invoke_agent medas                      [error]  connection to the record store was refused
├── chat openai/gpt-4.1-mini            [unset]  gen_ai.usage.input_tokens=2130
└── execute_tool search_patient_record  [error]  connection to the record store was refused
    └── retrieval record_chunks         [error]  connection to the record store was refused
```

`build_tree` in `reader.py` nests flat span rows under their parents, and refuses a trace with more than one root, a missing parent, or spans from two traces.

### Where traces are stored

- **The `spans` table**, written by the collector: one row per span, keyed by `trace_id` and `span_id`, with `app`, `name`, `kind`, timing, status, and `attributes` and `events` as JSONB. There is no `traces` table: a trace is the spans that share a `trace_id`.
- **The `scores` table**, written by the scoring job: one row per trace and check, with a value (0.0 bad, 1.0 fine) and the span the check blames, if any. Ids and numbers only.

## How traces get in: the collector

`POST /v1/traces` accepts an OpenTelemetry trace export (OTLP over HTTP), which is the default output of the OpenTelemetry exporters: an uncompressed binary protobuf `ExportTraceServiceRequest`.

```mermaid
flowchart LR
    a["Medas OTel exporter"] -- "application/x-protobuf" --> b["POST /v1/traces"]
    b --> c{"content type<br/>is protobuf?"}
    c -- no --> e1["415"]
    c -- yes --> d["decode(body)"]
    d -- "not an export" --> e2["400"]
    d --> f["keep spans whose<br/>service.name is in ALLOWED_APPS"]
    f --> g["INSERT ... ON CONFLICT DO NOTHING<br/>into spans"]
    g -- "database error" --> e3["503"]
    g --> h["200, empty<br/>ExportTraceServiceResponse"]
```

`decode` in `backend/api/traces.py` is a pure function that turns the export into rows:

- Trace and span ids become hex strings (32 and 16 characters).
- The status code becomes `unset`, `ok` or `error`; the span kind becomes a word such as `server`.
- Attributes become plain JSON: scalars and arrays are kept, any other value becomes null.
- Spans of an app outside `ALLOWED_APPS` (only `medas`) are dropped without an error.

A span that is already stored is left alone, so an exporter's retry changes nothing. A database failure is logged by exception type only, because a database error quotes the row.

The collector is the simplest version on purpose. It has no authentication, no body size limit, and strips nothing: clinical text is stored as sent. Use it only on localhost with synthetic traffic.

## How traces get out: the MCP server

The graph never queries a database. It reads traces through a read-only [FastMCP](https://gofastmcp.com) server, `backend/trace_store/mcp_server.py`.

```mermaid
sequenceDiagram
    participant G as Graph node
    participant C as TraceClient
    participant S as MCP server (subprocess, stdio)
    participant R as TraceReader

    Note over C,S: one subprocess and one session per run
    G->>C: search_failed_traces(app, since, until)
    C->>S: tools/call
    S->>S: TraceGuard counts the call, logs tool and argument hash
    S->>S: validate arguments, check app allowlist
    S->>R: search_failed_traces(query)
    R-->>S: TraceSummary rows
    S->>S: truncate free text
    S-->>C: structured result
    C-->>G: list of TraceSummary
    G->>C: get_trace_tree(trace_id)
    C->>S: tools/call
    S->>R: get_trace_tree(trace_id)
    R-->>S: SpanNode tree
    S->>S: redact and truncate attributes
    S-->>C: structured result
    C-->>G: SpanNode
```

`TraceClient` is `backend/agent/mcp_client.py`.

### The tools

| Tool | Input | Returns |
| --- | --- | --- |
| `search_failed_traces` | `FailedTraceQuery`: `app`, optional `since` (inclusive) and `until` (exclusive), `max_score`, `limit` (default 50, at most 200) | Failed traces as `TraceSummary` rows, newest first |
| `get_trace_tree` | `trace_id` | The whole span tree, string attributes cut to 200 characters |
| `get_span` | `trace_id`, `span_id` | One span without children, string attributes cut to 2,000 characters |

The graph uses the first two. `get_span` is served but `TraceClient` does not call it yet.

### The reader

The server's tools only call the three methods of the `TraceReader` protocol, so the data source can change without touching the tools. The one implementation in the app is `PostgresTraceReader`, over `spans` and `scores`; the server's own tests use a small in-memory one. It derives every summary field from what is stored: a failed trace is one whose lowest score is low, the failing span is the one that score blames, and the signature is that span's name and its exception type or, without one, the name of the check. Its session is read-only, but a dedicated read-only role does not exist yet.

### The scoring job

A request can fail without an error (a retrieval that finds nothing) and an error can be harmless (a call that was retried and worked), so "has an error span" is the wrong test for failed. `trace_store/scoring.py` scores each trace with plain code, no model: 0.0 is bad, 1.0 is fine, and a check that does not apply gives no score.

| Check | Scores 0.0 when |
| --- | --- |
| `request_failed` | The root span has status `error`. Every trace gets this score. It blames the deepest error span, the earliest of several |
| `timeout` | A tool call failed with a timeout and was not recovered |
| `tool_schema_error` | A tool call failed with a validation error and was not recovered |
| `tool_error` | A tool call failed with anything else that is not an expected error, and was not recovered |
| `empty_retrieval` | A retrieval ran without an error and reports 0 hits |

Recovered means a later call of the same tool in the trace succeeded. Expected errors are a short list in the code (`EXPECTED_ERRORS`, starting with a record that does not exist). Every bad score names the span it blames. A trace is scored once, right after its root span is stored, by the collector and by the seed script; spans that arrive later do not change its scores, and a trace with no scores is not served. Scoring is a step of its own: if it fails, the spans stay stored and the failure is logged. `uv run --env-file .env python -m trace_store.scoring` scores every trace that has no scores.

### What the server enforces

- **Read-only.** There are no write tools.
- **Sanitizing.** Only allowlisted attribute keys leave the server with their value: `gen_ai.request.*`, `gen_ai.response.*`, `gen_ai.usage.*`, and a few structural keys such as `retrieval.hits` and `exception.type`. Every other key keeps its name but its value becomes `[redacted]`, so a new Medas attribute is hidden until someone allows it. For example, `app.question` always reaches the agent as `[redacted]`. Status messages are the diagnoser's evidence, so they are truncated, not redacted.
- **Argument checks.** `search_failed_traces` serves only `ALLOWED_APPS`. Trace and span ids must match `^[A-Za-z0-9_.-]{1,64}$`, checked by pydantic before the tool runs.
- **Budget.** `TraceGuard` allows 300 tool calls per server process. `TraceClient` starts a fresh subprocess for each run, so that is a per-run budget. Rejected calls count too.
- **Audit log.** Every call is logged to stderr with the tool, the outcome and a hash of the arguments. Raw arguments, results and exception messages are never logged.

Two known limits: FastMCP's own "Invalid arguments" warning repeats a rejected id on stderr, and `get_trace_tree` and `get_span` take only ids, so only the Postgres reader scopes them to an app.

The session cannot outlive one graph invocation, so the resume after the human review opens no session. It gets `ClosedTraces`, whose every call raises, because that part of the run must read no traces.

## The agent graph

One LangGraph `StateGraph` over a shared `TriageState`, built by `build_graph` in `backend/agent/graph.py`.

```mermaid
flowchart TD
    start([START]) --> collect[collect_traces]
    collect -- "no failed traces" --> stop([END])
    collect --> cluster[cluster_failures]
    cluster -- "no clusters" --> stop
    cluster -- "one Send per cluster" --> diagnose["diagnose_cluster × N<br/>(parallel, at most 4 at once)"]
    diagnose --> join[join_diagnoses]
    join -- "clusters left unfinished<br/>by a transient error" --> diagnose
    join --> repro["reproduce_failure<br/>(placeholder)"]
    repro --> known["match_known_issues<br/>(placeholder)"]
    known --> draft[draft_proposals]
    draft --> review["human_review<br/>(interrupt: the run pauses)"]
    review -- "nothing approved" --> stop
    review -- "at least one approval" --> apply["apply_actions<br/>(dry run)"]
    apply --> stop
```

### Nodes

**`collect_traces`** asks the MCP server for the failed traces of `target_app`, optionally inside a `since`/`until` window, and stores the summaries as plain dicts in `failed_traces`. It uses the query's default limit, so a run sees at most the 50 newest failures. If nothing failed, the run ends.

**`cluster_failures`** groups the summaries with embeddings and HDBSCAN (see the next section). It makes no model call. It writes `clusters` and `unclustered`. Each unclustered trace also becomes a one-trace cluster with method `isolated`, so it is diagnosed like any other; there is no cap on these yet.

**`diagnose_cluster`** runs once per cluster, in parallel. A router sends each cluster as a `ClusterTask`, which holds the cluster and its spend so far, not the whole state. The node:

1. Fetches the span trees of the cluster's exemplars (the 3 newest traces) through the MCP server.
2. Makes one structured-output call that returns a `Diagnosis`: a category, a root cause, a suggested fix, a confidence between 0 and 1, and at least one piece of evidence (a trace id, a span id and a note). The system prompt is `agent/taxonomy.md`, which defines the ten categories.
3. Checks the evidence. Every cited span must be a span of the trees the model was shown. If one is not, the model is asked once more with the valid ids listed. If it still cites spans it was not shown, those are dropped, the confidence is capped at 0.3, and with no real citation left the cluster's own first failing span is cited. The stored diagnosis records the outcome in `evidence_check`: `valid`, `corrected` or `unsupported`.
4. Records its spend. Every run appends `{cluster_id, calls, tokens, cost_usd}` to `model_usage`, including failed runs.

Each cluster has a budget: 3 model calls, 100,000 tokens and 0.50 USD. A transient model error (408, 429, 5xx, a timeout, a dropped connection) with budget left leaves the cluster unfinished, and the graph runs the node again after a wait that doubles each time. Any other error, or an empty budget, puts the cluster id in `diagnosis_failures`. A failure is logged by exception type only.

**`join_diagnoses`** is the barrier after each round of parallel branches. The router after it sends back every cluster that has neither a diagnosis nor a recorded failure. Because the budget lives in state, the retry loop survives a resume, and because every run uses at least one attempt, it ends.

**`reproduce_failure`** is a placeholder. It will replay exemplar inputs against the target app. Until then every diagnosis is `unverified`, and no cluster is dropped for not reproducing.

**`match_known_issues`** is a placeholder. It will compare clusters with issues from earlier runs.

**`draft_proposals`** builds one `Proposal` per cluster, in cluster order, with no model call. The issue is markdown rendered with plain f-strings from the cluster and its diagnosis. A diagnosed cluster also gets a `RegressionCase` that holds ids only: the exemplar traces and the cited spans, never span text. A cluster without a diagnosis gets a stub proposal, so a failed cluster still reaches the reviewer. An evidence check other than `valid` is flagged in the issue body.

**`human_review`** pauses the run with `interrupt({"cluster_ids": [...]})`. The value holds ids only, because it is saved in the checkpoint and streamed. The run resumes on the same thread with one decision per proposal, `approve` or `reject`. If nothing is approved, the run ends without writing.

**`apply_actions`** is the only node that writes. For each approved proposal, the dry run writes `out/issues/<cluster_id>.md` and appends the regression case as one JSON line to `out/regression_cases.jsonl`, then returns the list of written paths as `actions_log`. With `dry_run` off it raises before any write, because the real writers do not exist.

### State

`TriageState` (`agent/state.py`) holds plain dicts, so checkpoints serialize without registering models:

| Field | Written by | Content |
| --- | --- | --- |
| `target_app`, `since`, `until` | the caller | What to triage |
| `failed_traces` | `collect_traces` | `TraceSummary` dicts |
| `clusters`, `unclustered` | `cluster_failures` | `Cluster` dicts; trace ids that fit no group |
| `diagnoses`, `diagnosis_failures`, `model_usage` | `diagnose_cluster` | Append-only lists, merged across the parallel branches |
| `reproductions`, `known_matches` | the placeholders | Fixed values for now |
| `proposals` | `draft_proposals` | `Proposal` dicts |
| `decisions` | `human_review` | Cluster id to `approve` or `reject` |
| `actions_log` | `apply_actions` | Paths written, relative to the output folder |

Per-run resources (the trace session, the embedder, the chat model, `dry_run`, the output folder) are not in state. They travel in `TraceContext`, passed at invoke time.

### Failure categories

`retrieval_miss`, `tool_schema_error`, `context_overflow`, `prompt_regression`, `model_quality`, `infra_error`, the three MAST top-level categories `system_design`, `inter_agent_misalignment` and `task_verification`, and `unknown`. The list is closed, and `agent/taxonomy.md` defines each one with a synthetic example.

## How clusters are found

Clustering is code, not model calls: `cluster_summaries` in `backend/agent/clustering.py` is pure and synchronous. Model calls happen once per cluster, never once per trace, so the cost of a run follows the number of distinct problems, not the number of failures.

```mermaid
flowchart TD
    a["Failed traces<br/>(TraceSummary)"] --> b{"fewer than 6?"}

    b -- no --> c["Failure text per trace:<br/>step, error, signature<br/>digits masked as #"]
    c --> d["Local embedding model<br/>bge-small-en-v1.5, 384 numbers per trace"]
    d --> e["HDBSCAN, cosine distance<br/>min_cluster_size 3, min_samples 4"]
    e -- "dense groups" --> f["Clusters<br/>method: hdbscan"]
    e -- "noise" --> g["Regroup by failing step<br/>and normalised error"]

    b -- "yes: skip embedding,<br/>everything goes to stage two" --> g

    g -- "group of 3 or more<br/>(any size in a small run)" --> h["Clusters<br/>method: step_error"]
    g -- "smaller group" --> i["Unclustered trace ids"]
    i --> j["One-trace clusters<br/>method: isolated"]

    f --> k["Sort biggest first,<br/>name c0, c1, …"]
    h --> k
    k --> l["clusters"]
    j -- "numbered after the real clusters" --> l
```

Step by step:

1. **Failure text.** Each trace becomes one short string, `<failing step>: <error message> | <signature>`, built only from fields already on the summary. Scores and timings are left out, and digits are masked as `#`, so values that differ between traces do not split one cause.
2. **Embedding.** `BAAI/bge-small-en-v1.5` runs locally through [fastembed](https://github.com/qdrant/fastembed) (ONNX Runtime on the CPU, about 65 MB, no API key). Similar failures get nearby vectors. The node runs it with `asyncio.to_thread`, off the event loop.
3. **HDBSCAN.** It finds dense groups without being told how many there are, and labels failures that fit no group as noise. The thresholds were tuned on a synthetic set of 26 summaries; `agent/const.py` records what was tried.
4. **Second stage.** HDBSCAN cannot see a single dense group: it labels the whole group noise. One fault often causes most of a run's failures, so the noise is regrouped by failing step and normalised error (digits and quoted values masked, so `missing 'dose'` and `missing 'unit'` count as one error). A group of 3 or more becomes a cluster.
5. **Small runs.** With fewer than 6 failed traces HDBSCAN has too little to work with. Embedding is skipped, the model is not loaded, and every step-and-error group becomes a cluster, because nothing can be called noise from so little data. The built-in fixture has two failed traces, so a run on it takes this path and yields two `step_error` clusters.
6. **Isolated failures.** A trace that fits no group becomes a cluster of one, so it is still diagnosed.

A `Cluster` holds `cluster_id` (`c0`, `c1`, … by size, stable for the same input), `trace_ids`, `signature` (the most common "failing step: normalised error" among its traces), `exemplar_trace_ids` (the 3 newest traces, which the diagnoser reads) and `method`.

### The embedding model

The weights are not in the repo. The first run with 6 or more failed traces downloads the model from Hugging Face and caches it in `FASTEMBED_CACHE_PATH`, or in a `fastembed_cache` folder in the system temp dir when that is not set. A reboot usually clears the temp dir, so point the variable at a lasting folder such as `$HOME/.cache/fastembed`. Once cached, the model loads without a network; `HF_HUB_OFFLINE=1` stops any contact with Hugging Face.

## Runs, review and the API

A run is one graph thread. Its state is checkpointed in Postgres, so a run that waits for review survives a restart. A `runs` row indexes it (status, counts, who started it), and `reviews` keeps one row per decided proposal. These tables hold ids, counts and decisions only, no issue text.

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Liveness |
| `POST /v1/traces` | The collector |
| `POST /v1/runs/stream` | Starts a run and streams it as server-sent events. Body: `target_app`, optional `since` and `until` |
| `GET /v1/runs` | The newest runs: ids, starter, status, counts |
| `GET /v1/runs/{run_id}` | One run: status, summary and proposals |
| `POST /v1/runs/{run_id}/review` | Resumes a paused run with one decision per proposal |

The stream sends `run_started`, then `progress` events (node, cluster id, counts; never state), one `proposal` event per draft, and last `review_required`, `run_completed` or `run_failed`. After most messages comes a `ui_spec`: a small model writes a UI description of the message, which the console draws.

A run's status is one of `in_progress`, `review_required`, `completed`, `failed` or `aborted`. Closing the stream before the review aborts the run. A review holds a row lock for the length of the resume, so a second review of the same run gets a `409`, and the decisions and the new status are committed together.

There is no login. The `X-User-Name` header is recorded as the starter or reviewer, not verified; without it the name is `local`.

## The run console

`frontend/` is one Next.js page with a form to start a run and a console with four tabs:

- **Runs** lists past runs. A run that waits for review has a Review button.
- **Console** draws the run's messages from the `ui_spec` events.
- **Raw events** shows the stream exactly as received.
- **Review** shows each proposal's issue with an Approve or Reject choice, and sends all decisions at once.

The page talks to the backend through a Next rewrite (`/api/*` to `/v1/*`), because the backend has no CORS.

## Safety rules

- Trace access is read-only and goes through the MCP server only.
- Raw span attributes do not reach the agent unless their key is allowlisted.
- All writes happen in `apply_actions`, and only for proposals a person approved.
- `dry_run` is on by default and set by the server (`DRY_RUN`), never by a request.
- Logs carry exception types and argument hashes, not messages or content.
- The issue text is the diagnoser's own prose. Nothing checks it for clinical content, so the human review is the gate. `backend/out/` is gitignored for the same reason.

## Running it

You need [uv](https://docs.astral.sh/uv/), Node.js, Docker and an [OpenRouter](https://openrouter.ai) API key.

Start Postgres (port 5433, localhost only):

```bash
docker compose up -d
```

Install the backend and create its environment file:

```bash
cd backend && uv sync && cp .env.example .env
```

Edit `backend/.env`: set `OPENROUTER_API_KEY`, and set `DATABASE_URL` to `postgresql://postgres:tracescan@127.0.0.1:5433/postgres` for the compose database.

Create the tables. The app does not migrate by itself and refuses to start before this has run:

```bash
cd backend && uv run --env-file .env alembic upgrade head
```

Start the backend (API docs at `http://localhost:8000/docs`):

```bash
cd backend && uv run --env-file .env uvicorn main:app --reload
```

Start the frontend, then open `http://localhost:3000`:

```bash
cd frontend && npm install && npm run dev
```

Start a run for `medas` from the page. It reads the stored traces (seed a day of them first, see below), diagnoses each cluster with the real model, and waits for your review. Approved proposals are written under `backend/out/`.

### Environment variables

| Variable | Required | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | yes | Postgres for the checkpoints and the application's tables |
| `TRACE_DATABASE_URL` | yes | Where the trace server reads spans and scores: the same database, meant for a read-only role |
| `OPENROUTER_API_KEY` | yes | The diagnoser's and the UI model's key |
| `DIAGNOSER_MODEL` | no | OpenRouter slug; default `anthropic/claude-sonnet-5-5` |
| `UI_SPEC_MODEL` | no | OpenRouter slug; default `anthropic/claude-haiku-5.5` |
| `JUDGE_MODEL` | no | The eval's judge; default `openai/gpt-6.1-sol` |
| `DRY_RUN` | no | On by default. Off is refused at startup |
| `FASTEMBED_CACHE_PATH` | no | Where the embedding model is cached |
| `BACKEND_URL` | no | For the frontend; default `http://localhost:8000` |

### Other entry points

Run the trace MCP server by itself over stdio (it needs `TRACE_DATABASE_URL`):

```bash
cd backend && uv run --env-file .env python -m trace_store.mcp_server
```

Fill `spans` with a day of synthetic Medas traffic, most of it failed, so a run can read from Postgres before Medas is instrumented:

```bash
cd backend && uv run --env-file .env python -m scripts.seed_traces
```

The day ends now unless `--end` gives another time; the same `--end` twice adds nothing. Runs read them only when `TRACE_DATABASE_URL` is set.

Run the eval on a seeded day (it needs `DATABASE_URL`, `TRACE_DATABASE_URL` and `OPENROUTER_API_KEY`). The first command seeds a fixed day, runs the triage up to the review pause and saves a results file under `backend/out/eval/`; the second has a model of another vendor grade each root cause from 0 to 2 against `eval/judge_rubric.md`; the third prints the scores:

```bash
cd backend && uv run --env-file .env python -m eval.run
```

```bash
cd backend && uv run --env-file .env python -m eval.judge
```

```bash
cd backend && uv run python -m eval.metrics
```

A seeded day is 48 traces of twelve kinds (`COUNTS` in `scripts/seed_traces.py`, answers in `eval/ground_truth.py`):

| Kind | Traces | What it tests |
| --- | --- | --- |
| `healthy` | 8 | Nothing wrong: nothing should be proposed |
| `source_timeout`, `tool_arguments`, `context_overflow`, `store_down` | 6, 5, 5, 1 | Plain faults, each with its own exception; `store_down` happens once |
| `model_unavailable` | 5 | One cause with two faces: the provider answers with a 5xx or does not answer at all |
| `tight_timeout` | 3 | A look-alike: the same step and exception as `source_timeout`, another cause (the tool's own 1 second timeout) |
| `double_failure` | 2 | Two errors in one request; the first one in the trace is not the cause |
| `unexplained` | 3 | Only the root span fails: the right answer is `unknown`, not a guess |
| `silent_no_hits` | 4 | A false negative: the retrieval finds nothing and no span fails |
| `retried_ok`, `not_found` | 3, 3 | False positives: an error span in a request that worked as it should |

The scores of one run on `anthropic/claude-sonnet-5-5`, judged by `openai/gpt-6.1-sol`, before and after the scoring job (different seeded days, so read the comparison per row with the notes):

| Score | Meaning | Before | With scores |
| --- | --- | --- | --- |
| Trace recall | Traces of a fault that reached a cluster at all | 30/34 | 34/34 |
| False alarms | Clusters that hold a trace with no fault | 1 | 0 |
| Detection | Seeded faults that are the majority of a diagnosed cluster | 6/9 | 5/9 |
| Purity | Traces that belong to their cluster's majority fault | 24/36 | 23/34 |
| Separation | Faults whose traces sit in one cluster that holds nothing else | 3/9 | 2/9 |
| Rare-failure recall | Faults seeded once that still got a diagnosis | 1/1 | 0/1 |
| Category accuracy | Diagnoses of a fault with its expected category | 6/6 | 4/5 |
| Evidence valid, relevant | Citations are real spans; they include the failing span | 6/6, 6/6 | 5/5, 5/5 |
| Cause accuracy | Diagnoses of a fault the judge scored 2: they name the injected cause | 6/6 | 5/5 |
| Cost and time | One run | 6 calls, $0.10, 11 s | 5 calls, $0.10, 16 s |

What it shows: the scoring job did what it was built for. The four failures with no error are now collected, and the six harmless requests with an error span are left out. What remains is the clustering, which now has every fault in front of it and still groups by failing step: the three kinds of PubMed timeout share a cluster, every chat failure shares another, and the silent retrieval misses share one with the single store outage, so the rare fault lost its own diagnosis. The diagnoser noticed that last cluster was mixed and answered `unknown` at 0.4 confidence instead of naming one cause. A diagnosis is judged against its cluster's majority fault, so cause accuracy says nothing about the faults buried in a mixed cluster: detection, purity and separation do. The judge's agreement with a person's grades (`python -m eval.judge --human c0=2 c1=1 ...`) is not measured yet.

[docs/eval-notes.md](docs/eval-notes.md) is the log of the eval experiments: the setup, both runs of the first one (plain faults, then the hard cases), the clusters it produced, the findings, the limits and what to do next.

## Tests and checks

Backend (what CI runs):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Tests never call a model and never download the embedding model: they use a fake chat model and `HashingEmbedder` from `tests/fakes.py`. Two groups of tests are opt-in (the diagnoser on the real model is the eval, `python -m eval.run`):

| Setting | Runs |
| --- | --- |
| `TEST_DATABASE_URL=...` | The Postgres tests: persistence, the run store, the collector, the reader, the scoring job, the trace client and the eval runner. CI sets it, with a Postgres service |
| `RUN_SLOW=1 uv run pytest -k fastembed` | Clustering with the real embedding model (downloads it once) |

Frontend:

```bash
cd frontend && npm run lint && npx tsc --noEmit && npm test && npm run build
```

## Repository layout

| Path | Content |
| --- | --- |
| `backend/agent/` | The graph, its nodes, clustering, the diagnoser's guards, the MCP client |
| `backend/trace_store/` | Trace contracts, Postgres reader, scoring job, MCP server, guard |
| `backend/runs/` | Run lifecycle and the run store |
| `backend/api/` | Runs API, the SSE stream, the UI spec call, the collector |
| `backend/db/`, `backend/migrations/` | Tables and Alembic migrations |
| `backend/main.py` | The FastAPI app and its startup wiring |
| `backend/tests/` | Tests and shared fakes |
| `frontend/` | The run console |
| `docker-compose.yml` | Local Postgres |
| `PLAN.md` | Scope, architecture decisions and task order |
| `CLAUDE.md` | Detailed notes on every module, for contributors and coding agents |
