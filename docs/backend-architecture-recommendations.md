# Backend architecture: recommendations

Saved from a design interview on 2026-11-10. **Applied so far:** the `PLAN.md` corrections (Q5), and the runs module with the review pause and its endpoints (Q6 to Q14). **Not applied:** the server-side `dry_run` setting and the real `apply_actions` (Q15, Q16), the trace server configuration (Q17) and the collector (Q4, Q18).

One difference from Q8 as written: `review_required` carries the run's summary, and the proposals travel as the `proposal` events just before it, so their text is not sent twice. All three rounds (Q1 to Q18) are answered: every recommendation is accepted except Q16, which was decided the other way.

Terms follow the codebase-design vocabulary: a **module** is anything with an interface and an implementation, a **seam** is where an interface lives, an **adapter** is a concrete thing that fills a seam, and a module is **deep** when a lot of behaviour sits behind a small interface.

## Status

| # | Decision | Recommendation | Status |
| --- | --- | --- | --- |
| Q1 | Scope of the design | Design for the planned pieces; restructure existing modules only where forced | **Accepted** |
| Q2 | Where a run lives | Single FastAPI process; the Postgres checkpointer is the only durable record | **Accepted** |
| Q3 | The MCP seam | Keep it as the only path from `agent/` to traces | **Accepted** |
| Q4 | Write side of traces | A module in `trace_store/`, same app, insert-only role | **Accepted** |
| Q5 | Which document is the truth | Code and `CLAUDE.md`; correct `PLAN.md` | **Accepted** |
| Q6 | A runs module | One module owns start, stream, status and resume; `api/runs.py` keeps HTTP and SSE | **Accepted** |
| Q7 | Run status | Read from the checkpoint; no `runs` table | **Accepted** |
| Q8 | Endpoints | Stream is the only start and ends in `review_required`; add `GET /v1/runs/{run_id}` and `POST /v1/runs/{run_id}/review`; remove sync `POST /v1/runs` | **Accepted** |
| Q9 | Trace session and the pause | Closes at the review pause; the resume opens none | **Accepted** |
| Q10 | Client leaves mid-run | Still aborts the run, up to the review pause | **Accepted** |

## Round 1

### Q1. Scope of the design (accepted)

**Decision:** design the target shape of the backend for the planned pieces (human review, `apply_actions`, the trace collector, the Postgres reader), and restructure existing modules only where one of those pieces forces it.

**Why:** the existing graph works and has 165 passing tests. Restructuring it for its own sake costs days needed before the day-10 MVP gate. The planned pieces will hit the weak spots anyway and show which ones matter.

### Q2. Where a run lives (accepted)

**Decision:** runs stay in the single FastAPI process. The Postgres checkpointer is the only durable record of a run, and a resume is a new request that invokes the graph again on the same `thread_id`.

**Why:** the checkpointer already makes a paused run durable, so nothing has to stay alive while a human reviews. A worker and a queue would add a second deployable and a second failure mode for no gain at capstone scale.

**Cost:** a run in progress dies with the process and must be restarted from its last checkpoint.

**Alternatives set aside:** a separate worker process fed by a queue; the LangGraph server owning runs.

### Q3. The MCP seam (accepted)

**Decision:** keep the stdio MCP server, one subprocess per run, as the only seam between `agent/` and `trace_store/`. Do not add an in-process shortcut for speed or simpler tests.

**Why:** it is a decided safety invariant that carries the read-only role, the per-run call budget and the audit log, and `test_boundaries.py` enforces it. A second path to the same data would need the budget and the audit log built twice.

### Q4. Where the write side of traces goes (accepted)

**Decision:** the collector (`POST /v1/traces`) is a module inside `trace_store/` with its own small interface (take an OTLP payload, store it). The same FastAPI app serves it, on a separate Postgres role with insert rights only, and `agent/` never imports it.

**Why:** one package then owns the `traces`, `spans` and `scores` schema for both writing and reading, so a schema change is made in one place. Three roles keep the safety story simple: the collector inserts, the MCP server reads, the checkpointer owns its own tables.

**Alternative set aside:** a separate collector service.

### Q5. Which document is the truth (accepted)

**Decision:** the code and `CLAUDE.md` are the truth. `PLAN.md` is corrected to match as part of this design's output. Done on 2026-11-10: the four places below are corrected, along with the stale task wording and checkboxes. The decisions of rounds 2 and 3 are not in `PLAN.md` yet.

`PLAN.md` has drifted in four places:

| `PLAN.md` says | The code does |
| --- | --- |
| `diagnose_cluster` is a `create_agent` with trace tools and a recursion limit (lines 56 and 262) | One structured-output call with no tools |
| `ClusterTask` is "target app plus one cluster" (line 78) | It carries the cluster plus its `model_usage` entries |
| `reproductions` and `actions_log` use append reducers (lines 72 and 75) | `state.py` gives them no reducer |
| A `ReproTask` type exists (line 78) | No such type in `agent/schemas.py` |

The missing reducers need a second look when `reproduce_failure` is designed, since it fans out in parallel like the diagnoser.

## Facts that bear on the open questions

From a read-only survey of `backend/` on 2026-11-10.

**Runs (Q2).**

- `api/runs.py` (170 lines) holds run orchestration and presentation together: building the graph input, making the thread id, building the runtime context, opening the trace client, calling the graph, counting results, SSE framing, the UI spec calls and their per-run cap.
- The sequence "open the trace client, call the graph, turn a failure into a 502" is written twice, once per endpoint. A resume endpoint would be a third copy.
- `run_id` and `thread_id` are the same value.
- `human_review` is a placeholder that approves cluster `c0`; it does not call `interrupt()`. `reproduce_failure`, `match_known_issues` and `apply_actions` are placeholders too.
- `agent/graph.py` has its own `main()` that builds the trace client, embedder and model, so there are two composition roots (`main.py` is the other).

**The trace seam (Q3).**

- `TraceClient()` takes no arguments. Its server command is the module constant `TRACE_SERVER`, which passes no environment to the subprocess.
- The server's `main()` hard-codes `FixtureTraceReader`. Nothing can yet tell the server which reader to use or give it a database URL.
- `TraceReader` has one production adapter (the fixture reader) and a test stub. The Postgres reader would be the second production adapter.
- `TraceClient` exposes `search_failed_traces` and `get_trace_tree`, not `get_span`.
- `api/runs.py` imports `TraceClient` at module level, so API tests patch `runs.TraceClient`.

**The interface of `agent/`.**

- There is no `agent/__init__.py`, so no export list. Production code outside `agent/` imports ten names from seven modules.
- Tests import many more: the route functions, the `diagnose_cluster` node (called directly), and the internals of `model_guard`, `evidence`, `clustering` and `proposals`. Some of these are internal seams with their own tests, which is fine; the routers and the node are tested past the graph's interface.
- `diagnose_cluster.py` (132 lines) has about 16 concerns across the node and its helper, and checks the budget in three places.

## Round 2 (accepted)

### Q6. A runs module

One module outside both `api/` and `agent/` owns the whole life of a run: start, stream its events, read its status, resume it with decisions. It takes the compiled graph, the embedder, the model and a way to open a trace session once, at startup, and hides the `thread_id`, the config dict and the `TraceContext` from callers. `api/runs.py` keeps only HTTP and SSE.

**Why:** that knowledge is spread across two endpoints and the test fixtures, and the review endpoints would need all of it again. API tests get one thing to fake.

### Q7. Run status without a runs table

A run's status is read from its checkpoint (which node is next, whether it waits at the review interrupt).

**Cost:** the backend cannot cheaply list runs. A client must keep its `run_id`; a "past runs" page would need a table later.

### Q8. The endpoints

- `POST /v1/runs/stream` is the only way to start a run. It ends with `review_required` (carrying the proposals) where it now ends with `run_completed`.
- `GET /v1/runs/{run_id}` returns status and proposals from the checkpoint.
- `POST /v1/runs/{run_id}/review` resumes with the decisions.
- The sync `POST /v1/runs` is removed.

### Q9. The trace session and the pause

The trace session and its MCP subprocess close when the run pauses for review. The resume opens none, because `apply_actions` writes only from approved proposals already in state. `TraceContext` must allow a run segment with no trace client, and `MAX_TOOL_CALLS` covers the segment before the pause.

### Q10. A client that leaves mid-run

A disconnect still aborts the run, up to the review pause. A run is durable only once it waits for review.

**Cost:** a dropped connection means starting again and paying again for the diagnoses already made.

## Consequences of Q1

- `diagnose_cluster.py` is left as it is: none of the planned pieces forces a change to it.
- Existing tests that call the routers and the node directly stay where they are.

## Round 3 (answered on 2026-11-10)

| # | Question | Decision | Status |
| --- | --- | --- | --- |
| Q11 | Interface of the runs module | `backend/runs/` with `start`, `status`, `review`; it yields typed run events, never raw graph state | **Accepted** |
| Q12 | Where UI spec calls live | Stay in `api/` as presentation; the per-run cap moves from the endpoint into `api/ui_spec.py` | **Accepted** |
| Q13 | Review request | One request with a decision for every proposal; `422` if incomplete, `409` if the run is not waiting for review | **Accepted** |
| Q14 | Review response | Plain JSON with the `actions_log`, not a stream | **Accepted** |
| Q15 | Who sets `dry_run` | The server (env, default true); a client cannot turn it off | **Accepted** |
| Q16 | Writers behind `apply_actions` | `apply_actions` branches on `dry_run` and calls the file or GitHub code directly; no writer seam | **Decided against the recommendation** |
| Q17 | Configuring the trace server | `TraceClient` takes its connection, built in `main.py`; the server picks the Postgres reader when its database URL is set, else the fixture | **Accepted** |
| Q18 | Collector: data and access | Store spans as received and keep the read-side sanitizer as the one filter; a static bearer token per app | **Accepted** |

### Q16. Writers behind `apply_actions`

**Recommended:** one writer seam with two adapters (dry-run files, and later GitHub plus the dataset).

**Decided:** no seam. `apply_actions` checks `dry_run` and calls the file-writing or the GitHub code directly.

**Why it is acceptable now:** the MVP has only the dry-run writer, so a seam would have a single adapter.

**Cost:** when the GitHub writer arrives (a stretch task), tests of the real branch must patch the GitHub calls, and the node holds both paths. Revisit then: two real writers are the point where the seam pays for itself.

### Open point from Q17

When the database URL is unset the server falls back to the fixture without saying so. It should log which reader it chose at startup, so a deployment that lost its URL is not mistaken for one with no failures.
