# TraceScan

TraceScan triages the failures of an LLM application. The application sends its traces to TraceScan over OpenTelemetry. On each run, TraceScan reads the traces of a time window, has a small model judge which requests failed, groups the failures into clusters, and has a larger model diagnose each cluster with cited spans. It then drafts one GitHub issue and one regression case per cluster. A person approves or rejects each draft, and only approved drafts are written.

It is the AI Engineering capstone. The first target app is **Medas**, a clinician-facing RAG assistant, which is instrumented in its own repo (`medas-api/tracing/` in `Nelev/medas`).

## Status

The pipeline runs end to end, on synthetic traces and on real Medas traffic, as a dry run.

| Part | State |
| --- | --- |
| OTLP collector (`POST /v1/traces` into the `spans` table) | Working, minimal: localhost and synthetic or test traffic only |
| Trace MCP server (read-only, sanitized, budgeted) | Working, over the Postgres reader |
| Graph: collect, judge, cluster, diagnose, draft, review, apply | Working |
| Graph: `reproduce_failure`, `match_known_issues` | Not built, not in the graph |
| Writes | Dry run only: local files under `backend/out/`. The GitHub and eval-dataset writers do not exist, and the app refuses to start with `DRY_RUN` off |
| Run console (Next.js) | Working: start and watch a run, list runs, open a run, browse traces, review proposals |
| Medas instrumentation | Working, in the Medas repo: one trace per agent run, no patient text on any span |
| Eval on seeded traces (`backend/eval/`) | Working, with a control day of no faults; the trace judge is scored too. Results below |
| Fault-injection eval in Medas | Not built |

`PLAN.md` holds the scope and the task order. `CLAUDE.md` has detailed notes on every module.

## Architecture

```mermaid
flowchart LR
    subgraph target["Target app (Medas)"]
        sdk["OpenTelemetry SDK<br/>BatchSpanProcessor<br/>OTLPSpanExporter"]
    end

    subgraph backend["TraceScan backend (FastAPI)"]
        collector["Collector<br/>api/traces.py"]
        browser["Trace browser API<br/>api/trace_browser.py"]
        api["Runs API + SSE<br/>api/runs.py"]
        uispec["UI spec call<br/>api/ui_spec.py"]
        runs["Runs module<br/>runs/"]
        agentgraph["LangGraph graph<br/>agent/"]
        api --> runs --> agentgraph
        api --> uispec
    end

    subgraph mcp["Trace MCP server<br/>(stdio subprocess, one per run)"]
        tools["search_traces<br/>get_trace_tree<br/>get_span<br/>+ TraceGuard"]
        reader["PostgresTraceReader<br/>read-only transactions"]
        tools --> reader
    end

    subgraph pg["Postgres"]
        spans[("spans<br/>scores")]
        apptables[("runs<br/>reviews")]
        cp[("graph checkpoints")]
    end

    ui["Run console<br/>Next.js"]
    llm["OpenRouter<br/>judge, diagnoser,<br/>UI spec models"]
    out[["out/issues/*.md<br/>out/regression_cases.jsonl"]]

    sdk -- "OTLP/HTTP protobuf<br/>POST /v1/traces" --> collector
    collector -- "INSERT … ON CONFLICT DO NOTHING" --> spans
    spans --> reader
    browser -- "read-only engine" --> spans
    agentgraph -- "TraceClient (MCP)" --> tools
    agentgraph --> llm
    uispec --> llm
    agentgraph -- "checkpointer" --> cp
    runs --> apptables
    agentgraph -- "apply_actions (dry run)" --> out
    ui -- "/api/* → /v1/*" --> api
    ui -- "/api/traces" --> browser
```

What each part owns:

- **`backend/api/traces.py`** is the collector: it takes OTLP exports and writes span rows. It does nothing else on the way in: no scoring, no filtering beyond the app allowlist.
- **`backend/trace_store/`** is the server side of trace access: the contracts (`models.py`), the `TraceReader` protocol and `build_tree`, the Postgres reader, the sanitizer, the MCP server and its guard.
- **`backend/agent/`** is the graph. It reaches traces only through the MCP client (`mcp_client.py`). It imports `trace_store.models` and nothing else from the server side, and no database driver; `tests/test_boundaries.py` enforces this.
- **`backend/runs/`** is the only code that knows a run is a graph thread. It starts runs, reads their status from the checkpoint, and resumes them at the review. Callers never get raw graph state.
- **`backend/api/`** is also HTTP and server-sent events over the runs module, and the read-only trace browser API.
- **`backend/db/`** and **`backend/migrations/`** hold the application's own tables (SQLAlchemy 2 and Alembic). LangGraph's checkpointer creates and owns its tables in the same database.
- **`frontend/`** is the web app: the runs, one run as it happens, and the stored traces.

## Traces and spans

A **trace** is one request to the target app: in Medas, one agent run. It is a tree of **spans**, one per step. Spans of the same trace share a `trace_id`; each span points at its parent with `parent_span_id`, and the root span has none.

### What a Medas trace looks like

Span names and attributes follow the OpenTelemetry [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/):

| Span name | Kind | What it is | Attributes |
| --- | --- | --- | --- |
| `invoke_agent medas` | server | The whole request, the root | `gen_ai.operation.name`, `gen_ai.agent.name` |
| `chat <model>` | client | One model call | `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` |
| `execute_tool <tool>` | internal | One tool call | `gen_ai.tool.name`, `gen_ai.tool.type` |
| `retrieval <source>` | client | A vector search inside a tool | `gen_ai.data_source.id`, `retrieval.hits` (how many passages came back) |

A failed span has status `error`, an `error.type` attribute (the exception's type) and, when the step raised, an `exception` event with `exception.type`. A Medas tool that catches a source's failure and tells the model about it without raising still gets status `error`, with `error.type` `ToolReportedError`. No prompt, answer, tool argument, tool result or passage text is put on any span.

A seeded trace whose record store is down:

```
invoke_agent medas                      [error]  error.type=sqlalchemy.exc.OperationalError
├── chat openai/gpt-4.1-mini            [unset]  gen_ai.usage.input_tokens=2130
└── execute_tool search_patient_record  [error]  error.type=sqlalchemy.exc.OperationalError
    └── retrieval record_chunks         [error]  error.type=sqlalchemy.exc.OperationalError
```

### The two views TraceScan reads

Both are Pydantic models in `backend/trace_store/models.py`.

**`SpanNode`**: one span with its children nested under it, as `get_trace_tree` returns it.

| Field | Meaning |
| --- | --- |
| `span_id`, `trace_id`, `parent_span_id` | Identity and position in the tree (hex: 16 and 32 characters) |
| `name` | The step, such as `execute_tool search_pubmed` |
| `kind` | OpenTelemetry span kind: `server`, `client`, `internal`, … |
| `start_time`, `end_time` | Timezone-aware timestamps |
| `status`, `status_message` | `unset`, `ok` or `error`, and the error text if any |
| `attributes` | Key and value pairs (scalars and arrays) |
| `events` | Timestamped events, each `{name, time, attributes}` |
| `children` | Child spans, ordered by start time |

`build_tree` in `trace_store/reader.py` nests the flat rows under their parents, and refuses a trace with more than one root, a missing parent, or spans of two traces. A trace that is not whole yet (no root, or a missing parent) has no tree.

**`TraceSummary`**: one small row per trace, from the root span only, as `search_traces` returns it:

```json
{
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "app": "medas",
  "start_time": "2026-11-11T09:00:00Z",
  "duration_ms": 2400.0,
  "status": "error",
  "signature": "invoke_agent medas"
}
```

Once the trace judge says a trace failed, `join_scores` fills in its failure fields from the blamed span: `failing_span_id`, `failing_span_name`, `error_message` (the status message), `min_score` (the judge's score) and a new `signature`, the blamed step and its error type (`execute_tool search_pubmed httpx.ReadTimeout`). The signature holds names only, no message and no attribute value, and is what the clustering embeds.

## How an app sends traces

Any app can send traces with a stock OpenTelemetry SDK and the OTLP/HTTP exporter. Three things are required:

1. **Protocol:** OTLP over HTTP with binary protobuf (`http/protobuf`), uncompressed, to `POST <backend>/v1/traces`. gRPC and the JSON encoding are not accepted.
2. **Resource:** `service.name` must be an app in `ALLOWED_APPS` (`backend/trace_store/const.py`, only `medas` today). Spans of any other service are dropped without an error.
3. **Content:** names, counts, model ids, token usage and error types. The collector strips nothing, so the app itself must keep personal and clinical text off its spans.

In Python, as Medas does it (`medas-api/tracing/runtime.py`):

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider(resource=Resource({"service.name": "medas"}))
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:8010/v1/traces"))
)
tracer = provider.get_tracer("medas.tracing")

with tracer.start_as_current_span("invoke_agent medas") as root:
    root.set_attribute("gen_ai.operation.name", "invoke_agent")
    ...
provider.shutdown()  # at app shutdown: send what is still queued
```

`BatchSpanProcessor` sends spans in batches from a background thread, so a request never waits for the collector, and a collector that is down loses spans, not requests. Medas builds its spans from LangChain's callbacks (`TraceHandler` in `medas-api/tracing/handler.py`), so the agent code knows nothing of tracing; tracing is off unless `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set.

Any other language works the same way with the standard exporter variables:

```bash
OTEL_SERVICE_NAME=medas
OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8010/v1/traces
```

To run Medas and TraceScan side by side on one machine, run TraceScan on ports 8010 and 3010 (see [Running it](#running-it)).

### The OTLP protocol, as the collector reads it

The body is one `ExportTraceServiceRequest` protobuf message (from `opentelemetry-proto`). Its shape, and what the collector keeps of it:

```mermaid
flowchart TD
    req["ExportTraceServiceRequest"] --> rs["resource_spans[]"]
    rs --> res["resource.attributes<br/><b>service.name</b> → app<br/>(must be in ALLOWED_APPS)"]
    rs --> ss["scope_spans[]<br/>(one per instrumentation scope)"]
    ss --> sp["spans[]"]
    sp --> f1["trace_id: 16 bytes → 32 hex chars<br/>span_id, parent_span_id: 8 bytes → 16 hex chars"]
    sp --> f2["name, kind (enum → server, client, internal, …)"]
    sp --> f3["start/end_time_unix_nano → timestamptz (µs)"]
    sp --> f4["status.code (enum → unset, ok, error)<br/>status.message"]
    sp --> f5["attributes: KeyValue[] of AnyValue<br/>→ JSON: string, bool, int, double, array; else null"]
    sp --> f6["events[]: name, time, attributes"]
```

The exchange:

```mermaid
sequenceDiagram
    participant A as App (OTel SDK)
    participant C as Collector POST /v1/traces
    participant P as Postgres (spans)

    A->>C: Content-Type: application/x-protobuf<br/>ExportTraceServiceRequest
    alt another content type
        C-->>A: 415
    else body is not an export
        C-->>A: 400
    else
        C->>C: decode(body): rows for allowed apps only
        C->>P: INSERT … ON CONFLICT DO NOTHING
        alt database error
            C-->>A: 503 (logged by exception type only)
        else
            C-->>A: 200, empty ExportTraceServiceResponse
        end
    end
```

`decode` is pure and `store_spans` returns how many spans were new. A span already stored is left alone, so an exporter's retry changes nothing.

The collector is the simplest version on purpose: no authentication, no body size limit, no partial-success count, and nothing stripped. Use it only on localhost.

## How traces are stored

Traces live in the application's Postgres, in the same database as the run tables and the graph checkpoints.

**`spans`** (migration `0003`), written by the collector, one row per span:

| Column | Type | Note |
| --- | --- | --- |
| `trace_id` | `varchar(32)` | Primary key, with `span_id` |
| `span_id` | `varchar(16)` | |
| `parent_span_id` | `varchar(16)` | Null on the root |
| `app` | `varchar` | The resource's `service.name` |
| `name`, `kind` | `varchar` | |
| `start_time`, `end_time` | `timestamptz` | |
| `status` | `varchar(10)` | Checked: `unset`, `ok` or `error` |
| `status_message` | `varchar` | |
| `attributes` | `jsonb` | |
| `events` | `jsonb` | A list of `{name, time, attributes}` |

An index on `(app, start_time DESC)` serves the window queries. There is no `traces` table: a trace is the spans that share a `trace_id`, and its summary comes from its root span.

**`scores`** (migration `0004`): one row per trace and check (`trace_id`, `evaluator`, `value` from 0.0 bad to 1.0 fine, the blamed `span_id`, `scored_at`). The trace browser reads it. Nothing writes it for now: which traces failed is decided by the trace judge inside each run, and its verdicts stay in the run's state.

**Reading.** `PostgresTraceReader` (`trace_store/postgres_reader.py`) is the only reader. Its engine opens every transaction read-only (a dedicated read-only role is planned, not created yet). It serves only `ALLOWED_APPS`. The trace MCP server uses it for the graph, and the trace browser API uses it for the app's trace pages.

## How the graph reads traces: the MCP server

The graph never queries the database. It reads traces through a read-only [FastMCP](https://gofastmcp.com) server, `backend/trace_store/mcp_server.py`, which `TraceClient` starts as a stdio subprocess, one per run.

| Tool | Input | Returns |
| --- | --- | --- |
| `search_traces` | `TraceQuery`: `app`, optional `since` (inclusive) and `until` (exclusive), `limit` (at most 200) | Every trace with a root span in the window, as `TraceSummary` rows, newest first |
| `get_trace_tree` | `trace_id` | The whole `SpanNode` tree, string attributes cut to 200 characters |
| `get_span` | `trace_id`, `span_id` | One span without children, string attributes cut to 2,000 characters (served, not used by the graph yet) |

What the server enforces:

- **Read-only.** There are no write tools, and the reader's transactions are read-only.
- **Sanitizing.** Only allowlisted attribute keys keep their value: `gen_ai.request.*`, `gen_ai.response.*`, `gen_ai.usage.*`, and structural keys such as `gen_ai.tool.name`, `retrieval.hits`, `error.type` and `exception.type`. Every other key keeps its name and reads `[redacted]`, so a new attribute is hidden until someone allows it. Status messages are truncated, not redacted.
- **Argument checks.** `search_traces` serves only `ALLOWED_APPS`; ids must match `^[A-Za-z0-9_.-]{1,64}$`, checked by pydantic before the tool runs.
- **Budget.** `TraceGuard` allows 500 tool calls per server process, which is one run: one search, one tree per judged trace, and the diagnoser's exemplar trees.
- **Audit log.** Every call is logged on stderr with the tool, the outcome and a hash of the arguments, never the raw arguments, results or exception messages.

The session cannot outlive one graph invocation, so the resume after the human review opens none: it gets `ClosedTraces`, whose every call raises.

## The agent graph

One LangGraph `StateGraph` over `TriageState`, built by `build_graph` in `backend/agent/graph.py`. Two steps fan out with `Send`: the trace judge runs once per trace, the diagnoser once per cluster.

```mermaid
flowchart TD
    start([START]) --> collect["collect_traces<br/>search_traces: every trace in the window"]
    collect -- "no traces" --> stop([END])
    collect -- "one Send(TraceTask) per trace" --> judge["score_trace × T<br/>trace judge, up to 16 at once"]
    judge --> joins["join_scores<br/>barrier: failed traces, newest first"]
    joins -- "nothing failed" --> stop
    joins --> cluster["cluster_failures<br/>embeddings + HDBSCAN, no model call"]
    cluster -- "no clusters" --> stop
    cluster -- "one Send(ClusterTask) per cluster" --> diagnose["diagnose_cluster × N<br/>diagnoser, at most 4 at once"]
    diagnose --> draft["draft_proposals<br/>issue + regression case per cluster"]
    draft --> review["human_review<br/>interrupt: the run pauses"]
    review -- "nothing approved" --> stop
    review -- "at least one approve" --> apply["apply_actions<br/>dry run: local files"]
    apply --> stop

    classDef llm fill:#1e3a8a,stroke:#60a5fa,color:#fff
    classDef human fill:#78350f,stroke:#f59e0b,color:#fff
    class judge,diagnose llm
    class review human
```

Blue nodes call a model; the amber node waits for a person. `reproduce_failure` (replay exemplars against the app) and `match_known_issues` (compare with earlier issues) are planned before `draft_proposals` and not built; until the reproducer exists every diagnosis is `unverified`, and no cluster is dropped for not reproducing.

### The nodes

**`collect_traces`** (`nodes/collect_traces.py`) calls `search_traces` for `target_app` in the optional `since`/`until` window, up to `MAX_JUDGED_TRACES` (200) newest traces, failed or not. It stores them as plain dicts in `traces`. An empty window ends the run.

**`score_trace`** (`nodes/score_trace.py`, `judge.py`) is the trace judge, one parallel branch per trace with a `TraceTask` holding only that trace. "Has an error span" is the wrong test for failed: a retrieval can find nothing without an error, and an error can be harmless (a retried call, a lookup that correctly finds nothing). So the branch fetches the sanitized tree and makes one structured call on `TRACE_JUDGE_MODEL` (Haiku by default) with `judge_prompt.md`. The model answers a `TraceVerdict`: a reason, a score from 0.0 to 1.0, the span where the failure started, and whose fault it is (`app`, `external` or `unclear`). The code decides "failed" (score at most 0.5). A failed verdict must blame a span of the tree: if it does not, the model is asked once more with the valid ids, then the code blames the deepest error span (`blame_check`: `valid`, `corrected` or `fallback`). A failed verdict also gets the blamed span's name, error type and status message. Any error puts the trace id in `judge_failures`; every branch appends its spend to `judge_usage`. Budget per trace: 3 calls, 20,000 tokens, 0.05 USD.

**`join_scores`** (`graph.py`) is the barrier after the judge branches. It keeps the traces whose verdict says failed, turns each into a `TraceSummary` with the failure fields and the step-and-error signature (`judge.failed_summary`), and writes `failed_traces`, newest first. Nothing failed: the run ends.

**`cluster_failures`** (`nodes/cluster_failures.py`, `clustering.py`) groups the failed traces with code, not model calls (see the next section), off the event loop. It writes `clusters` and `unclustered`, and turns each unclustered trace into a one-trace cluster (`method` `isolated`), so every failure is diagnosed.

**`diagnose_cluster`** (`nodes/diagnose_cluster.py`) runs once per cluster with a `ClusterTask` holding only the cluster, at most 4 at once. See [How a cluster is diagnosed](#how-a-cluster-is-diagnosed).

**`draft_proposals`** (`nodes/draft_proposals.py`, `proposals.py`) runs once after every diagnose branch, with no model call. It renders one `Proposal` per cluster in cluster order: a title (`[<category>] <signature>`) and a markdown issue with the sections Summary, Evidence, Suspected cause, Suggested fix and Verification status. A diagnosed cluster also gets a `RegressionCase` of ids only (exemplar traces and cited spans, never span text). A cluster whose diagnosis failed gets a stub proposal (`[undiagnosed] …`), so it still reaches the reviewer. An evidence check other than `valid` is flagged in the body.

**`human_review`** (`graph.py`) pauses the run with `interrupt({"cluster_ids": [...]})`, ids only, since the value is checkpointed and streamed. The run resumes on the same thread with `Command(resume={cluster_id: "approve" | "reject"})`, one decision per proposal. Nothing approved: the run ends without writing.

**`apply_actions`** (`nodes/apply_actions.py`, `actions.py`) is the only node that writes, and only approved proposals. As a dry run it writes `out/issues/<cluster_id>.md` and appends each regression case as one JSON line to `out/regression_cases.jsonl`, and returns the paths as `actions_log`. With `dry_run` off it raises before any write, because the real writers do not exist.

### State and context

`TriageState` (`agent/state.py`) holds plain dicts, so checkpoints serialize without registered models. Fields filled by parallel branches are append-only (`Annotated[list, operator.add]`).

| Field | Written by | Content |
| --- | --- | --- |
| `target_app`, `since`, `until` | the caller | What to triage |
| `traces` | `collect_traces` | Every `TraceSummary` in the window |
| `verdicts`, `judge_failures`, `judge_usage` | `score_trace` (append) | One verdict per judged trace; traces whose judging failed; spend per trace |
| `failed_traces` | `join_scores` | Failed traces with their failure fields |
| `clusters`, `unclustered` | `cluster_failures` | `Cluster` dicts; trace ids that fit no group |
| `diagnoses`, `diagnosis_failures`, `model_usage` | `diagnose_cluster` (append) | One diagnosis per cluster; clusters that failed; spend per cluster |
| `proposals` | `draft_proposals` | `Proposal` dicts |
| `decisions` | `human_review` | Cluster id to `approve` or `reject` |
| `actions_log` | `apply_actions` | Paths written, relative to the output folder |

Per-run resources are not in state. They travel in `TraceContext` (`agent/context.py`), passed at invoke time: the trace session, the embedder, the diagnoser's and the judge's chat models, the diagnose semaphore, `dry_run` and the output folder.

## How failures become clusters

Clustering is code: `cluster_summaries` in `backend/agent/clustering.py` is pure and synchronous. Model calls happen once per cluster, so the diagnoser's cost follows the number of distinct problems, not the number of failures.

```mermaid
flowchart TD
    a["Failed traces<br/>(TraceSummary from join_scores)"] --> b{"fewer than 6?"}

    b -- no --> c["Failure text per trace:<br/>'step: error message | signature'<br/>digits masked as #"]
    c --> d["Local embedding model<br/>bge-small-en-v1.5 (fastembed, CPU)<br/>384 numbers per trace"]
    d --> e["HDBSCAN, cosine distance<br/>min_cluster_size 3, min_samples 4"]
    e -- "dense groups" --> f["Clusters<br/>method: hdbscan"]
    e -- "noise" --> g["Regroup by failing step<br/>and normalised error"]

    b -- "yes: skip embedding" --> g

    g -- "3 or more traces<br/>(any size in a small run)" --> h["Clusters<br/>method: step_error"]
    g -- "fewer" --> i["Unclustered trace ids"]
    i --> j["One-trace clusters<br/>method: isolated"]

    f --> k["Sort biggest first,<br/>name c0, c1, …"]
    h --> k
    k --> l["clusters"]
    j -- "numbered after the others" --> l
```

1. **Failure text.** Each failed trace becomes one short string, `<failing step>: <error message> | <signature>`, from fields already on the summary. Digits are masked as `#`, so values that differ between traces do not split one cause. Scores and timings are left out.
2. **Embedding.** `BAAI/bge-small-en-v1.5` runs locally through [fastembed](https://github.com/qdrant/fastembed) (ONNX Runtime, about 65 MB, no API key), so similar failures get nearby vectors.
3. **HDBSCAN** finds dense groups without being told how many, and labels failures that fit none as noise. The thresholds were tuned on a synthetic set; `agent/const.py` records what was tried.
4. **Second stage.** HDBSCAN cannot see one single dense group (it labels it all noise), and one fault often causes most of a run's failures. So the noise is regrouped by failing step and normalised error (quoted values and digits masked, so `missing 'dose'` and `missing 'unit'` are one error). A group of 3 or more becomes a cluster.
5. **Small runs.** With fewer than 6 failed traces, embedding is skipped and every step-and-error group becomes a cluster, since nothing can be called noise from so little data.
6. **Isolated failures.** A trace that fits no group becomes a cluster of one, so it is still diagnosed.
7. **Cluster map.** The same embeddings are projected to 3D for the run page: identical embeddings in the same cluster become one point, PCA is always tried and t-SNE too from 30 distinct points, and the map keeps the one with the higher trustworthiness (how well near neighbours stay near; stored as `trust`). HDBSCAN worked on all 384 dimensions, so the map is a picture of the space, not the space. It holds trace ids, coordinates and labels, never the failure text. Small runs have no map.

A `Cluster` holds `cluster_id` (`c0`, `c1`, … by size, stable for the same input), `trace_ids`, `signature` (the most common "step: normalised error" among its traces), `exemplar_trace_ids` (the 3 newest traces, which the diagnoser reads) and `method` (`hdbscan`, `step_error` or `isolated`).

The model weights are not in the repo. The first run with 6 or more failures downloads them into `FASTEMBED_CACHE_PATH` (default: a `fastembed_cache` folder in the system temp dir, which a reboot may clear; `$HOME/.cache/fastembed` lasts). Once cached, `HF_HUB_OFFLINE=1` stops any contact with Hugging Face.

## How a cluster is diagnosed

The diagnoser is a plain structured-output call, not a tool-using agent: the node fetches the evidence itself and hands it to the model.

```mermaid
flowchart TD
    t["ClusterTask (one cluster)"] --> s["Wait for one of 4 diagnose slots"]
    s --> f["Fetch the exemplar trees<br/>get_trace_tree × 3 (sanitized)"]
    f -- "fetch fails" --> fail["diagnosis_failures"]
    f --> p["Prompt: taxonomy.md as system,<br/>cluster size + signature + exemplar trees"]
    p --> m["with_structured_output(Diagnosis)<br/>DIAGNOSER_MODEL via OpenRouter"]
    m -- "transient error (408, 429, 5xx, timeout)<br/>and budget left" --> w["wait, doubling"] --> m
    m -- "other error / no budget" --> fail
    m --> c{"every cited span<br/>in the trees shown?"}
    c -- yes --> v["evidence_check: valid"]
    c -- "no, budget left" --> r["Ask again,<br/>listing the valid ids"]
    r --> c2{"all valid now?"}
    c2 -- yes --> co["evidence_check: corrected"]
    c2 -- no --> u["evidence_check: unsupported<br/>drop invalid citations,<br/>confidence capped at 0.3,<br/>none left → cite the cluster's first failing span"]
    c -- "no, budget spent" --> u
    v --> out["diagnoses + model_usage"]
    co --> out
    u --> out
    fail --> usage["model_usage (failed spend counts too)"]
```

1. **Evidence.** The node fetches the span trees of the cluster's 3 exemplar traces once, through the MCP server, so the model sees only sanitized attributes.
2. **The call.** One `with_structured_output(Diagnosis)` call on `DIAGNOSER_MODEL` (Sonnet by default), with `agent/taxonomy.md` as the system prompt. A `Diagnosis` holds a `category` from the closed taxonomy, a `root_cause`, a `suggested_fix`, a `confidence` from 0 to 1, and at least one `Evidence` (a trace id, a span id and a note). The code sets `cluster_id` itself.
3. **Citation check.** Every cited span must be a span of the trees the model was shown. If not, the model is asked once more with the valid ids. If it still cites spans it was not shown, they are dropped and the confidence is capped at 0.3; with no real citation left, the cluster's first failing span is cited. The result's `evidence_check` (`valid`, `corrected`, `unsupported`) is set by the code, never by the model.
4. **Retries and budget.** Each cluster has 3 model calls, 100,000 tokens and 0.50 USD. A transient error is retried after a doubling wait while the budget holds; the SDK's own retries are off, so all retrying is here. Any other error, or an empty budget, puts the cluster in `diagnosis_failures`, logged by exception type only. The node appends one `{cluster_id, calls, tokens, cost_usd}` entry to `model_usage` over all its attempts, with the cost OpenRouter reports.

The failure categories: `retrieval_miss`, `tool_schema_error`, `context_overflow`, `prompt_regression`, `model_quality`, `infra_error`, the MAST top-level `system_design`, `inter_agent_misalignment` and `task_verification`, and `unknown`. `agent/taxonomy.md` defines each one.

## Guards on the agent

The agent reads clinical traces, calls paid models and drafts text that may be written somewhere. Every one of those steps has a guard written in code, so it does not depend on the model behaving. The guards sit at five points:

```mermaid
flowchart LR
    subgraph access["1 · Trace access"]
        a1["import boundary<br/>test_boundaries.py"]
        a2["MCP only, read-only<br/>transactions"]
        a3["app allowlist,<br/>TraceId pattern"]
        a4["TraceGuard:<br/>500 calls, audit log"]
        a5["sanitizer:<br/>attribute allowlist"]
    end
    subgraph calls["2 · Model calls"]
        b1["Budget per item:<br/>calls, tokens, cost"]
        b2["retry transient<br/>errors only"]
        b3["timeout, SDK<br/>retries off"]
        b4["concurrency caps<br/>16 / 4"]
    end
    subgraph answers["3 · Model answers"]
        c1["schema validation"]
        c2["blame check<br/>(judge)"]
        c3["citation check<br/>(diagnoser)"]
        c4["code sets ids<br/>and verdicts"]
    end
    subgraph failures["4 · Failures"]
        d1["one branch fails,<br/>the others go on"]
        d2["failed items kept,<br/>never dropped"]
    end
    subgraph writes["5 · Writes"]
        e1["human review<br/>interrupt"]
        e2["one decision per<br/>proposal, row lock"]
        e3["dry run only"]
        e4["safe file names"]
    end
    access --> calls --> answers --> failures --> writes
```

### 1. Trace access

| Guard | Where | What it stops |
| --- | --- | --- |
| Import boundary | `tests/test_boundaries.py` | `agent/` importing a database driver, the Postgres saver or any `trace_store` module except `models`: the agent can reach traces only through the MCP client |
| Read-only server | `trace_store/mcp_server.py`, `postgres_reader.py` | Writes: there is no write tool, and every reader transaction is read-only |
| Argument checks | `TraceQuery`, `TraceId` in `trace_store/models.py` | Another app's traces (`ALLOWED_APPS`, checked in `search_traces`; the reader scopes the id lookups too), and ids of any shape other than `^[A-Za-z0-9_.-]{1,64}$`, rejected by pydantic before the tool runs. A search returns at most 200 rows |
| Call budget | `TraceGuard` in `trace_store/guard.py` | A runaway loop of tool calls: 500 per server process, which is one run. Rejected calls count too; past the budget every call is `denied` |
| Audit log | `TraceGuard` | Silent access: every call is logged with the tool, the outcome and a hash of its arguments, never the arguments, results or exception messages |
| Sanitizer | `trace_store/sanitize.py` | Clinical text reaching a model: attribute values outside the allowlist read `[redacted]`, and strings are cut to 200 characters in a tree |
| Closed session on resume | `ClosedTraces` in `agent/context.py` | Trace reads after the review: the resume gets a trace access whose every call raises |

### 2. Model calls

All of it is in `agent/model_guard.py`, shared by the trace judge and the diagnoser.

| Guard | What it does |
| --- | --- |
| Budget per item | Each trace and each cluster has its own `Spent` (calls, tokens, cost) and `Budget`. `Spent.ok` is checked before any second call. Trace: 3 calls, 20,000 tokens, 0.05 USD. Cluster: 3 calls, 100,000 tokens, 0.50 USD. A call is counted before it is made, so a call that raises still counts. Tokens and cost come from what OpenRouter reports |
| Transient errors only | `retryable` allows 408, 429, 5xx, timeouts and dropped connections. Anything else is a bug and is raised at once |
| Backoff | `retrying` waits 1 s before the first retry and doubles the wait after each, and retries one call at a time, so an answer already received is never asked for again. The diagnoser uses it; the judge makes one attempt plus its blame re-ask |
| One retry layer | The SDK's own retries are off (`max_retries=0`), and each request has a 120 s timeout, so a call that hangs becomes a timeout that the budget controls |
| Window cap | A run judges at most `MAX_JUDGED_TRACES` (200) traces, the newest first |
| Concurrency | At most 16 branches run at once (`max_concurrency`), and at most 4 diagnoses (a semaphore in `TraceContext`), so N clusters never mean N large calls at the same time |
| Spend on record | Every branch appends its spend to `judge_usage` or `model_usage`, failed attempts included, and the run page shows it |

### 3. Model answers

| Guard | What it does |
| --- | --- |
| Schema validation | Both models answer through `with_structured_output(..., method="json_schema")`, and the answer is validated by pydantic (`TraceVerdict`, `Diagnosis`: closed category list, confidence between 0 and 1, at least one piece of evidence). An answer that doesn't parse raises |
| Blame check | A failed verdict must blame a span of the tree the judge was shown. Otherwise the judge is asked once more with the valid ids, and then the code blames the deepest error span (`blame_check`: `valid`, `corrected`, `fallback`) |
| Citation check | Every span the diagnoser cites must be in the exemplar trees it was shown. Otherwise it is asked once more. Citations it still can't back up are dropped, the confidence is capped at 0.3, and the cluster's first failing span is cited if nothing is left (`evidence_check`) |
| The code decides | The model gives a score, and the code decides "failed" (at most 0.5). The code sets `cluster_id`, `evidence_check` and `blame_check`. Verification stays `unverified` until a reproducer exists |
| No content in prompts back | A re-ask sends ids only, never span contents |

### 4. Failures

A judge or diagnose branch catches its own errors. It records the trace id in `judge_failures` or the cluster id in `diagnosis_failures`, logs the exception type only (a message could quote span contents), and returns normally, so one failure never stops the other branches. A cluster without a diagnosis still gets a stub proposal, so the reviewer sees it. Isolated failures become one-trace clusters instead of being dropped.

### 5. Writes

| Guard | Where | What it stops |
| --- | --- | --- |
| Human review | `human_review` (`interrupt`) | Any write without a person: the run pauses before `apply_actions`, and the interrupt value holds ids only, because it is checkpointed and streamed |
| Complete decisions | `Runs.review` in `runs/service.py` | A partial review: exactly one `approve` or `reject` per proposal, otherwise `422` with the `missing` and `unknown` cluster ids |
| One review at a time | `PostgresRunStore.reviewing` | Two reviews of one run: a row lock (`FOR UPDATE SKIP LOCKED`) makes the second get `409`, and the decisions and the new status commit together or not at all |
| Approved only | `apply_actions` | Rejected proposals being written, or becoming "known" |
| Dry run only | `require_dry_run` in `agent/actions.py` | Real writes before the writers exist: the app refuses to start with `DRY_RUN` off, and `apply_actions` raises before writing. No request can change the setting |
| Safe file names | `write_dry_run` | Path tricks: a cluster id that is not `[A-Za-z0-9_-]+` raises before anything is written |
| Ids-only regression cases | `proposals.py` | Span text in the eval dataset: a regression case holds trace and span ids only |

The UI spec model, which runs next to the graph, has its own limits: at most 40 calls per run (`MAX_UI_CALLS_PER_RUN`) and 15 s per call. A message that goes past either is sent without a spec.

What is not guarded yet: the diagnoser's prose is not checked for clinical content (the human review is the gate), the collector has no authentication or size limit, and no read-only database role exists.

## Runs, review and the API

A run is one graph thread. Its state is checkpointed in Postgres (`AsyncPostgresSaver`), so a run that waits for review survives a restart. A `runs` row indexes it (window, status, counts, who started it) and `reviews` keeps one row per decided proposal: ids, counts and decisions only, no issue text. A run's status is `in_progress`, `review_required`, `completed`, `failed` or `aborted`; closing the stream before the review aborts the run.

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Liveness |
| `POST /v1/traces` | The collector |
| `GET /v1/traces`, `GET /v1/traces/{trace_id}` | The trace browser: trace rows, and one sanitized tree with its scores |
| `POST /v1/runs/stream` | Starts a run (`target_app`, optional `since`, `until`) and streams it as server-sent events |
| `GET /v1/runs` | The newest runs: ids, starter, status, counts |
| `GET /v1/runs/{run_id}` | One run: status, summary and proposals |
| `GET /v1/runs/{run_id}/detail` | One run's pipeline and clusters with their diagnoses and spend |
| `POST /v1/runs/{run_id}/review` | Resumes a paused run with one decision per proposal |

The stream sends `run_started`, `progress` events (node, counts; never state), one `proposal` event per draft, and last `review_required`, `run_completed` or `run_failed`. Behind most messages comes a `ui_spec`: a small model (`UI_SPEC_MODEL`) describes the message as a [json-render](https://github.com/vercel-labs/json-render) spec, which the run page's agent console checks and draws.

A review holds a row lock for the length of the resume, so a second review of the same run gets a `409`, and the decisions and the new status are committed together. Every route except `/health` and the trace collector needs a Clerk session token (`Authorization: Bearer`): `401` without a valid one, `503` when it cannot be verified. A run or a review is recorded under the name the token carries (its `name` claim, else `email`, else Clerk's user id). The web app signs in with Clerk and sends that token on every call.

## The web app

`frontend/` is a Next.js app with a slim left nav and three kinds of page. **New run**, in the header, opens a small form (app, time window) and takes you to the run's page once the server names it.

- **Dashboard** (`/`, the landing page): the runs waiting for your review in one line, four figures (the latest run's failure rate, failed traces found in the last 7 days, open proposals, how long the oldest review has waited), what the newest analyzed run found (failed traces by category, its five largest clusters), failed traces per run over the last runs (each bar opens its run), how the week's runs ended, and the latest run's diagnosis spend.
- **Runs** (`/runs`): every run with its funnel (failed traces → clusters → proposals), duration and who started it.
- **Run** (`/runs/<id>`): one run, live or finished. A pipeline stepper (Collect → Judge → Cluster → Diagnose → Draft → Review → Apply) shows where it stands and what each stage produced, driven by the stream while it runs. Below it, one card per cluster: signature, category, confidence, evidence check and root cause. Opening a card shows the suggested fix, the cited evidence as span trees of the traces the diagnoser was shown (cited spans starred), the drafted issue and the cluster's traces. While the run waits, each card takes Approve or Reject and a sticky bar sends all decisions at once. Beside it, the **agent console** draws the run's messages from the `ui_spec` events (json-render), with a Raw events toggle for the stream as received.
- **Traces** (`/traces`, `/traces/<id>`): the stored traces with their app and the cluster each one landed in (over the last five analyzed runs), and one trace as a span tree over its timeline with the picked span's attributes and links to its clusters on their run pages.

The page reaches the backend through a Next rewrite (`/api/*` to `/v1/*`), because the backend has no CORS.

## Safety rules

- Trace access is read-only and goes through the MCP server only.
- Span attributes reach a model only if their key is allowlisted.
- All writes happen in `apply_actions`, and only for proposals a person approved.
- `dry_run` is on by default and set by the server (`DRY_RUN`), never by a request.
- Logs carry exception types and argument hashes, never messages or content.
- The issue text is the diagnoser's own prose. Nothing checks it for clinical content, so the human review is the gate; `backend/out/` is gitignored for the same reason.

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

Edit `backend/.env`: set `OPENROUTER_API_KEY` and `CLERK_SECRET_KEY` (from the TraceScan application in the Clerk dashboard), and set `DATABASE_URL` and `TRACE_DATABASE_URL` to `postgresql://postgres:tracescan@127.0.0.1:5433/postgres` for the compose database.

Create the tables (the app never migrates by itself and refuses to start before this):

```bash
cd backend && uv run --env-file .env alembic upgrade head
```

Start the backend (API docs at `http://localhost:8000/docs`):

```bash
cd backend && uv run --env-file .env uvicorn main:app --reload
```

Start the frontend, then open `http://localhost:3000` and sign in. It needs the same Clerk application's keys: copy `frontend/.env.example` to `frontend/.env.local` and fill in `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY`. In the Clerk dashboard, restrict sign-up to invited accounts and add `{"name": "{{user.full_name}}", "email": "{{user.primary_email_address}}"}` to the session token (Sessions → Customize session token), so runs are recorded under your name.

```bash
cd frontend && npm install && npm run dev
```

With no real app sending traces, seed a day of synthetic Medas traffic (52 traces, healthy and failed):

```bash
cd backend && uv run --env-file .env python -m scripts.seed_traces
```

**Next to Medas.** Medas uses ports 8000, 3000 and 5433 too. Run TraceScan's backend on 8010 and its frontend on 3010 (the `backend-8010` and `frontend-3010` entries in `.claude/launch.json`; build the frontend with `BACKEND_URL=http://localhost:8010` first), set Medas's `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to `http://localhost:8010/v1/traces`, and move Medas's database with `DATABASE_PORT` in `medas-api/.env`.

### Environment variables

| Variable | Required | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | yes | Postgres for the checkpoints, the run tables and the collector's writes |
| `TRACE_DATABASE_URL` | yes | Where the trace server and trace browser read spans: the same database, meant for a read-only role |
| `OPENROUTER_API_KEY` | yes | The key for every model call |
| `CLERK_SECRET_KEY` | yes | Clerk's secret key; every API route but `/health` and the collector needs a session token |
| `CLERK_JWT_KEY` | no | Clerk's JWT public key (PEM), to verify tokens without a network call |
| `CLERK_AUTHORIZED_PARTIES` | no | JSON list of origins a token may be issued for; default the UI on 3010 and 3000 |
| `DIAGNOSER_MODEL` | no | Default `anthropic/claude-sonnet-5-5` |
| `TRACE_JUDGE_MODEL` | no | The per-trace judge; default `anthropic/claude-haiku-5.5` |
| `UI_SPEC_MODEL` | no | Default `anthropic/claude-haiku-5.5` |
| `JUDGE_MODEL` | no | The eval's grader (not the trace judge); default `openai/gpt-6.1-sol` |
| `DRY_RUN` | no | On by default. Off is refused at startup |
| `FASTEMBED_CACHE_PATH` | no | Where the embedding model is cached |
| `BACKEND_URL` | no | For the frontend; default `http://localhost:8000` |

### The eval

The eval runs the triage on a seeded day whose answers are known (it needs `DATABASE_URL`, `TRACE_DATABASE_URL` and `OPENROUTER_API_KEY`). The first command seeds a fixed day and runs up to the review pause, the second has a model of another vendor grade each root cause against `eval/judge_rubric.md`, the third prints the scores (detection, purity, separation, recall, category and cause accuracy, evidence validity, cost):

```bash
cd backend && uv run --env-file .env python -m eval.run
```

```bash
cd backend && uv run --env-file .env python -m eval.judge
```

```bash
cd backend && uv run python -m eval.metrics
```

A seeded day has twelve kinds of traces (`COUNTS` in `scripts/seed_traces.py`, answers in `eval/ground_truth.py`): healthy requests, plain faults, and hard cases (a look-alike timeout, a fault with two faces, a request with two errors of which the first is not the cause, a failure at the root only, a retrieval that silently finds nothing, and harmless error spans). [docs/eval-notes.md](docs/eval-notes.md) logs every experiment and its results. [docs/eval/review.md](docs/eval/review.md) sums them up for review, and [docs/eval/eval-results.xlsx](docs/eval/eval-results.xlsx) holds every run's scores, the clusters, the answer key and the rubrics.

A control day (`python -m eval.run --control`) seeds only healthy requests and harmless errors, so anything it finds is a false alarm. `eval.metrics` also scores the trace judge on its own (which traces it called failed, per kind) and counts its spend in the cost.

#### Results

The latest runs (experiment 5 in the notes): a fault day the judge prompt was not tuned on, and the control day. One run each, so a single trace can change a ratio.

| Score | Fault day (2026-02-27) | Control day |
| --- | --- | --- |
| Trace judge: faulty traces caught | 34/34 | n/a |
| Trace judge: harmless traces flagged | 0/18 | 1/52 |
| Detection (faults with a diagnosed cluster) | 6/9 | n/a |
| Cluster purity | 27/34 | 1/1 |
| Cause separation | 2/9 | n/a |
| Rare-failure recall | 0/1 | n/a |
| False alarms (clusters with no fault) | 0 | 1 |
| Category accuracy | 5/6 | n/a |
| Root-cause accuracy (graded on the injected cause) | 5/6 | n/a |
| Evidence valid and relevant | 6/6, 6/6 | 1/1, 1/1 |
| Cost and time | $0.13 (judge $0.03), 25 s | $0.04 (judge $0.03), 22 s |

The weak spot is clustering: look-alike timeouts merge, and the rare store outage joins the silent retrieval misses.

## Tests and checks

Backend (what CI runs):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright -p .. && uv run pytest
```

Tests never call a model and never download the embedding model: they use fake chat models and `HashingEmbedder` from `tests/fakes.py`. The Postgres tests run with `TEST_DATABASE_URL` (CI sets it); `RUN_SLOW=1 uv run pytest -k fastembed` repeats the clustering check with the real embedding model.

Frontend:

```bash
cd frontend && npm run lint && npx tsc --noEmit && npm test && npm run build
```

## Repository layout

| Path | Content |
| --- | --- |
| `backend/agent/` | The graph, its nodes, the trace judge, clustering, the diagnoser's guards, the MCP client |
| `backend/trace_store/` | Trace contracts, Postgres reader, sanitizer, MCP server, guard |
| `backend/runs/` | Run lifecycle and the run store |
| `backend/api/` | The collector, the trace browser, the runs API and SSE stream, the UI spec call |
| `backend/db/`, `backend/migrations/` | Tables and Alembic migrations |
| `backend/scripts/seed_traces.py` | Synthetic Medas traffic |
| `backend/eval/` | Ground truth, eval runner, grader, metrics |
| `backend/main.py` | The FastAPI app and its startup wiring |
| `backend/tests/` | Tests and shared fakes |
| `frontend/` | The web app: dashboard, runs, run pages, traces |
| `docker-compose.yml` | Local Postgres |
| `PLAN.md` | Scope, architecture decisions and task order |
| `CLAUDE.md` | Detailed notes on every module, for contributors and coding agents |
