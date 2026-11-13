<!--
Claude Code: this is the project plan for TraceScan (capstone, AI Engineering course).
Use it as the source of truth for scope and task order:
- Work through "Implementation plan" phase by phase; tick a task's checkbox when its "Done when" check passes.
- Keep the MVP tight. Do not start stretch tasks before the MVP gate check passes.
- MVP proposals are "unverified"; never drop a cluster because it did not reproduce.
- Trace access is read-only (MCP server on a read-only DB role). All writes happen only in apply_actions, after human approval, with dry_run on by default.
- The code lives in backend/agent/ (the graph) and backend/trace_store/ (trace contracts, reader, MCP server); there is no tracescan/ package.
- Where this plan and the code disagree, the code and CLAUDE.md are right: correct the plan.
-->

# TraceScan — AI Agent for LLM Failure Triage

Nov 2, 2026 · @Mattia

## Overview

TraceScan is a multi-agent system that acts as an on-call engineer for an LLM application. It reads the app's traces, groups the failures, diagnoses why each group happened, states how far each diagnosis has been verified, and drafts a GitHub issue plus a regression test for a human to approve.

The problem it solves: observability tools show what happened in each run, but a developer still has to scroll through hundreds of failed traces to find the pattern. TraceScan turns that into a short report, for example: "38 failures this week fall into 3 groups; group A is the retriever returning nothing for drug-interaction questions; here are the cited spans, a draft issue and a test case."

It is built as the AI Engineering capstone project, with Medas (the clinician-facing RAG assistant) as the first target app.

## Solution

TraceScan runs a fixed triage pipeline instead of an open chat: collect failures, cluster them, diagnose each cluster, optionally replay it, check it against known issues, then propose actions that a human approves.

The closest existing tool is Halo, the Langfuse assistant, which explores project data and takes actions in Langfuse with the user's approval ([Langfuse docs](https://langfuse.com/docs/halo.md)). Chatting with traces is therefore not new. TraceScan differs in five ways:

- **Batch triage, not Q&A**: it works across all failures in a time window and groups them, rather than answering one question at a time.
- **Taxonomy-based diagnosis**: each cluster gets a category from a fixed list, with the trace spans cited as evidence.
- **Verification status**: every proposal states how far it was checked: unverified in the MVP; confirmed, flaky or unconfirmed once replay is added. Nothing is dropped for failing to reproduce.
- **Memory of known issues**: repeat failures update an existing issue instead of creating duplicates.
- **Closing the loop**: every approved issue comes with a regression case added to the eval dataset.

TraceScan also depends on no observability platform. Medas is instrumented with OpenTelemetry and sends its traces to a collector and store that are part of this project, so the whole path from trace to fix is my own code.

Failure categories combine common single-agent causes (retrieval miss, tool schema error, context overflow, prompt regression, model quality, infrastructure error) with the three top-level categories of the Berkeley MAST taxonomy for multi-agent systems: system design issues, inter-agent misalignment and task verification ([arXiv 2503.13657](https://arxiv.org/abs/2503.13657)).

## Architecture

TraceScan is a single LangGraph graph of eight nodes, with two stages that fan out in parallel and one pause for human approval.

```text
TraceScan MCP (read-only) --read--> collect_traces
                                    cluster_failures      (embeddings + HDBSCAN in code; isolated failures kept as `unclustered`; ends if there are none at all)
                                    diagnose_cluster  x N (one structured-output call per cluster and per unclustered failure, in parallel; reads the exemplar span trees)
                                    [join]                (waits for all diagnoses; sends unfinished clusters back for a retry)
Medas sandbox  <--replay--          reproduce_failure x N (stretch: replays inputs; MVP marks every diagnosis "unverified")
Known-issues store --lookup-->      match_known_issues    (links clusters to issues from earlier runs)
                                    draft_proposals       (create or update issue; shows verification status)
                                    human_review          (interrupt(); ends if nothing is approved)
GitHub + eval dataset <--write--    apply_actions         (approved items only; dry run by default; also updates the store)
                                    END
```

Stacked boxes run once per item in parallel: one diagnosis per cluster and one per unclustered failure (not capped yet, see Clustering), one replay per diagnosis. The join node waits for every diagnosis of a round, sends back each cluster that has neither a diagnosis nor a failure, and lets reproduction start once none is left. The run ends early if there are no failures at all (no clusters and nothing unclustered) or if the reviewer approves nothing. In the MVP the reproduce step only marks each diagnosis as unverified; replay against Medas is a stretch goal.

Inside the graph, `diagnose_cluster` is a plain node, not an agent. It fetches the span trees of the cluster's exemplar traces through the read-only trace server, then makes one structured-output call (`with_structured_output(Diagnosis)`) with the taxonomy as the system prompt. The model gets no tools. Retries are the graph's own loop (`diagnose_cluster` → join → `diagnose_cluster`) under a per-cluster budget of attempts, tokens and cost that is kept in state, so they survive a resume. If the diagnoser ever needs tools, it moves to `create_agent(response_format=Diagnosis)` with a low recursion limit. The outer pipeline stays a plain `StateGraph`, so order, parallelism, batch approval and evaluation remain fixed.

## State and data model

One shared state object flows through the graph; the three fields filled by the parallel diagnose branches use an append reducer so results are merged, not overwritten.

| Field | Type | Written by | Notes |
| --- | --- | --- | --- |
| `target_app`, `since`, `until` | str | input | Which app and time window to triage; `since` and `until` are optional |
| `failed_traces` | list\[TraceSummary\] | collect\_traces | Compact view of each failed or low-score trace |
| `clusters` | list\[Cluster\] | cluster\_failures | Groups with a signature and a few exemplar traces |
| `unclustered` | list\[str\] | cluster\_failures | Ids of isolated failures; each is also a one-trace cluster (`method` `isolated`) and is diagnosed on its own |
| `diagnoses` | list\[Diagnosis\], append reducer | diagnose\_cluster (parallel) | Category, root cause, fix, confidence, evidence spans |
| `diagnosis_failures` | list\[str\], append reducer | diagnose\_cluster (parallel) | Ids of clusters whose diagnosis failed; reported, not dropped |
| `model_usage` | list\[dict\], append reducer | diagnose\_cluster (parallel) | One entry per diagnose run, failed or not: calls, tokens and cost; the per-cluster budget is checked against it |
| `reproductions` | list\[dict\] | reproduce\_failure | Unverified in the MVP; with replay, confirmed, flaky or unconfirmed. No reducer yet: it needs an append reducer once the replay fans out in parallel |
| `known_matches` | dict cluster → issue id | match\_known\_issues | Links to issues from earlier runs |
| `proposals` | list\[Proposal\] | draft\_proposals | Create or update issue, body, regression case |
| `decisions` | dict cluster → approve/reject | human\_review | Supplied by the reviewer on resume |
| `actions_log` | list\[str\] | apply\_actions | What was written, or would be in dry run |

State holds plain dicts, not Pydantic objects, so checkpoints serialize without a warning.

Parallel branches do not receive the whole state. Each diagnose branch gets a small `ClusterTask` (one cluster plus that cluster's `model_usage` entries, because a node reached through `Send` sees only its payload), which keeps prompts short. The reproduce branches will get a `ReproTask` (cluster plus its diagnosis) in the same way; that type does not exist yet.

The diagnoser returns a Pydantic `Diagnosis` through structured output, so its category must be one of the allowed values and it carries a list of the trace spans it is based on.

## Clustering

Clustering is code, not LLM calls: local embeddings (FastEmbed, which runs on ONNX Runtime and needs no GPU) feed HDBSCAN, and a second stage regroups the noise by failing step and error type. Three rules keep it honest.

- **Embed a clean failure summary, not the raw trace.** The text is the failing operation, the error message and the relevant span context. IDs, timestamps, numbers and quoted values are masked so they do not pull unrelated failures together or push identical ones apart, while the error wording itself is kept. Scores and timings stay out. Nothing in it may carry clinical content.
- **Similar wording is not the same cause.** Two different faults can fail with near-identical messages, and one fault can surface in different words. The fault-injection eval checks both directions: traces from one injected fault should share a cluster, and traces from different faults should not.
- **Nothing isolated is lost.** Failures that fall in no cluster stay in `unclustered` and each gets its own diagnosis, so a rare issue reaches the reviewer. This is the one exception to "LLM calls per cluster, not per trace", and it is not capped yet: if a real run shows too many isolated failures, add a per-run cap and list the ids over it in the run summary, so nothing is silently dropped.

The approach stays as it is until the eval shows a need. Only then add complexity (a different model, a reranking step, an LLM pass over borderline clusters).

## Tools and safety

Three nodes touch the outside world: one reads traces, one replays inputs in a sandbox, and one writes, and the write node runs only after a human approves.

| Tool | Type | Used by | Safeguard |
| --- | --- | --- | --- |
| TraceScan MCP server over the trace store (search traces, get trace tree, get span) | Read | collect\_traces, diagnose\_cluster | Read-only database role, a per-run call budget and an audit log |
| Target app API in a sandbox | Execute | reproduce\_failure | Replays exemplar inputs only, N attempts each |
| GitHub issues (create, comment) | Write | apply\_actions | Approved proposals only |
| Eval dataset (add regression case) | Write | apply\_actions | Approved proposals only |
| Known-issues store | Write | apply\_actions | Updated after an approved action |

The trace reader is a small MCP server built with FastMCP on top of the trace store. It offers three tools (`search_traces`, `get_trace_tree`, `get_span`) and connects to Postgres with a read-only database role, so it cannot change data whatever the agent asks. Both the collector node and the diagnoser node use it, and the model itself never calls it. Until the Postgres store exists, the server reads the synthetic fixture.

The human gate is LangGraph's `interrupt()` in the `human_review` node. The graph pauses with the list of proposals, the reviewer resumes it with an approve or reject per cluster, and only approved items reach `apply_actions`. If nothing is approved, the graph ends without writing anything.

A `dry_run` setting makes `apply_actions` write local files (`out/issues/`) instead of calling GitHub. The server sets it (an environment variable, on by default) and no request can turn it off. It is used for demos and eval runs.

## Tracing stack

Instead of an observability platform, TraceScan comes with its own small tracing stack built on OpenTelemetry, the vendor-neutral standard for traces.

```text
Medas (OTel SDK, gen_ai.* attributes) --OTLP/HTTP--> Trace collector (FastAPI, POST /v1/traces)
                                                            | spans
                                                            v
Scoring job (heuristics; LLM judge = stretch) <--> Postgres trace store (spans, scores tables)     
                                                     |                        |
                                          read-only role                    reads
                                                     v                        v
                               TraceScan MCP server (FastMCP)          Next.js UI (trace viewer, error feed)
                                                     | tools
                                                     v
                               TraceScan graph (collect_traces, diagnose_cluster)
```

Medas sends spans over the standard OTLP protocol to a FastAPI collector, which stores them in Postgres; TraceScan never touches the database directly, only through its read-only MCP server.

| Component | What it does | Built with |
| --- | --- | --- |
| Instrumentation in Medas | One trace per request; spans for retrieval, each tool call and generation, using the standard `gen_ai.*` attribute names plus prompt version, retrieval count and request id | OpenTelemetry Python SDK, LangChain/LangGraph auto-instrumentation where available |
| Trace collector | Receives OTLP over HTTP, decodes it and writes spans | FastAPI, `opentelemetry-proto` |
| Trace store | Two tables: spans (ids, parent id, app, name, kind, timing, status, attributes and events as JSONB; a trace is the spans that share a trace id) and scores (trace, evaluator, value, blamed span) | Postgres, the same instance as checkpoints and memory |
| Scoring job | Marks bad answers that raised no error: heuristic checks on every trace (MVP), and as a stretch an LLM judge for groundedness on every failure and a 10% sample of successes | Python worker, structured output |
| MCP server | `search_traces`, `get_trace_tree`, `get_span` for the agent | FastMCP, read-only database role |
| UI | Trace list with a span-tree view, and an error feed of TraceScan's clusters | Next.js |

The sampling rule (all failures, about 10% of successes) follows Comet's guidance on agent tracing ([Comet blog](https://www.comet.com/site/blog/ai-agent-tracing/)). Because Medas handles clinical questions, the collector can also strip personal data from span attributes before storing them. During the first days, the same OTLP traces can go to a local Jaeger container to inspect them before the own viewer exists.

## Memory

TraceScan uses two separate kinds of memory: a checkpointer for the state of one run, and a store for knowledge that lasts across runs.

| Kind | LangGraph component | Scope | Holds | Why |
| --- | --- | --- | --- | --- |
| Short-term | Checkpointer (`InMemorySaver`, then `PostgresSaver`) | One run, keyed by `thread_id` | Full graph state at every step | Lets the run pause at human review and resume hours later |
| Long-term | Store (`InMemoryStore`, then `PostgresStore`) | All runs, namespaced by target app | Known issues: cluster signature → issue id | Turns repeat failures into issue updates, not duplicates |

In the sketch, the known-issues lookup is an exact match on the cluster signature. The real version uses the store's semantic search, so a cluster described slightly differently still matches the right issue. The store is only written after an approved action, so rejected proposals never become "known".

## Evaluation

TraceScan is measured two independent ways: on bugs deliberately injected into the target app, where the right answer is known, and on a published benchmark of labelled multi-agent failures.

**1. Fault injection in Medas.** Known bugs are introduced one at a time, each triggered by several different input sets, and TraceScan is asked to find them. Healthy runs with no fault switched on serve as controls, where TraceScan should propose nothing. Planned faults:

- Retriever returns zero chunks for one question category
- A tool's input schema no longer matches what the model sends
- System prompt truncated so a key instruction is lost
- Context window set too small for long documents
- Model swapped for a weaker one
- Upstream API timeout on a share of calls

Each diagnosis is graded on whether it names the actual cause (for example, the retriever's filter excludes the drug-interaction category) rather than only describing the symptom (answers come back empty). The ground-truth file records both for every fault.

**2. MAST-Data benchmark (stretch).** MAST-Data holds 1,642 annotated traces from seven multi-agent frameworks, plus MAST-Data-human, 21 traces each labelled by three experts ([arXiv 2503.13657](https://arxiv.org/abs/2503.13657)). The diagnoser classifies these traces and its labels are compared with the published ones. The paper's own LLM annotator reached 94% accuracy and a Cohen's kappa of 0.77 against experts, which gives a reference point.

| Metric | Definition | Source |
| --- | --- | --- |
| Detection rate | Injected faults that appear as a cluster or are diagnosed from `unclustered` | Fault injection |
| Cluster purity | Clusters whose traces all come from one injected fault | Fault injection |
| Cause separation | Injected faults whose traces stay in separate clusters from other faults, including look-alike ones | Fault injection |
| Rare-failure recall | Low-volume faults that reach a diagnosis through `unclustered` | Fault injection |
| Root-cause accuracy | Clusters given the correct category and cause | Fault injection |
| False positives | Proposals not linked to any injected fault | Fault injection |
| Duplicate rate | Repeat failures filed as new issues | Fault injection, second run |
| Label agreement | Accuracy and Cohen's kappa vs human labels | MAST-Data-human |
| Cost and time | Tokens, dollars and minutes per triage run | TraceScan's own traces in the same store |
| False alarms on healthy runs | Proposals raised during control runs with no fault | Healthy control runs |
| Cause vs symptom | Diagnoses that name the injected cause, not just the visible symptom | Fault injection, graded against the ground-truth file |

TraceScan traces its own runs into the same trace store, so its cost and failures are observable the same way as the target app's.

**First results (2026-11-10), on seeded traces, before Medas has fault switches.** The eval in `backend/eval/` grades a run against synthetic traces whose causes are known: five plain faults, then hard cases (a look-alike, one cause with two faces, two errors in one request, a failure with no visible cause, a failure with no error, and errors that are not faults). On the plain faults every score is full marks, which says little. With the hard cases the diagnoser is still right about every cluster it is given (category 6/6, cause 6/6, and `unknown` where the trace shows no cause), but the clustering merges look-alike failures and harmless errors into one cluster (detection 6/9, purity 24/36, separation 3/9), and the failure with no error is never collected (trace recall 30/34). So the next work on quality is the clustering and the scoring job, not the diagnoser. With the scoring job built, trace recall is 34/34 and the harmless errors are no longer collected; the clustering still groups by failing step (detection 5/9, separation 2/9), so it is what is left. The log is in `docs/eval-notes.md`; this does not replace the fault-injection eval in Medas described above.

## Tech stack and running it

The stack is Python with LangGraph 1.x for orchestration and its own OpenTelemetry trace store; the graph sketch already runs end to end on LangGraph 1.2 with stubbed nodes.

| Layer | Choice | Role |
| --- | --- | --- |
| Orchestration | LangGraph 1.x | Graph, parallel fan-out, interrupts, checkpointing |
| Observability | OpenTelemetry SDK, own FastAPI collector, Postgres trace store | Traces of the target app and of TraceScan itself |
| Trace access | Own MCP server (FastMCP), read-only role | Tool layer for the collector |
| Data models | Pydantic | Structured LLM output and validated state |
| Clustering | Local embeddings (FastEmbed, ONNX) + HDBSCAN | Grouping failures without LLM calls; isolated failures kept for individual diagnosis |
| Persistence | Postgres checkpointer and store | Paused runs and known issues in deployment |
| Issue tracker | GitHub API | Draft and update issues |
| Dev UI | LangGraph Studio (`langgraph dev`) | Step through nodes, inspect state, approve at the pause |
| Review UI | Next.js (App Router, TypeScript) over the FastAPI backend | Runs list, run detail, approve or reject proposals, eval results |
| Diagnoser | One structured-output call per cluster through OpenRouter (`langchain-openrouter`) | Diagnoses each cluster from its exemplar span trees |



To run it in LangGraph Studio: compile the graph without a local checkpointer and store (the server provides persistence), point `langgraph.json` at the module's `graph` variable, and start `langgraph dev`. Studio then shows the graph and offers the resume step at the human review node.

## Scope and build plan

The MVP shows one path end to end: failed traces in, evidence-backed issue proposals out, measured by the fault-injection eval, done by day 10 of 16. The collector, store and viewer stay as small as that path needs; everything else is optional.

**MVP (must ship)**

- [ ] Medas traced with OpenTelemetry into the own trace store, plus a script that generates realistic and adversarial traffic
- [x] Minimal trace collector, Postgres store, heuristic scoring and read-only MCP server
- [x] Clustering of failures with embeddings and HDBSCAN, isolated failures kept for individual diagnosis
- [x] Diagnoser with structured output and the failure taxonomy
- [x] Human review gate with approve or reject per proposal
- [x] Draft issues written to markdown files (dry run)
- [ ] Fault-injection eval with six seeded bugs, varied inputs, healthy control runs and the metrics table; proposals marked unverified
- [x] Minimal trace viewer in Next.js: plain trace list and span tree

**Stretch (if time allows)**

- [ ] Replay-based reproducer in a sandbox
- [ ] Known-issues memory with semantic matching
- [x] Real GitHub issue creation
- [ ] MAST-Data agreement study
- [ ] Scheduled daily triage run and a deployed demo
- [ ] Next.js review dashboard over the FastAPI backend (runs list, run detail, trace viewer and review screen built; results page open)
- [ ] LLM judge for groundedness in the scoring job

The phases below are in working days, since no start date is fixed yet.

| Phase | Days | Focus | MVP? |
| --- | --- | --- | --- |
| Foundations | 1–2 | Repo, trace collector and store, Medas instrumentation, traffic script, MCP server | Yes |
| Core agents | 3–5 | Clustering, taxonomy, diagnoser, evidence check, scoring job | Yes |
| Loop and eval | 6–10 | Proposals, human review, dry-run actions, fault injection with controls, metrics | Yes |
| **Gate: MVP complete, day 10** | | Six faults run, controls run, metrics table filled | |
| Stretch | 11–14 | Reproducer, known-issues memory, GitHub, MAST-Data, review UI | No |
| Ship | 15–16 | Postgres persistence, deploy, README, demo video, buffer | Yes |

The first three phases make up the MVP; if the gate slips, the stretch phase shrinks first and the ship phase is protected.

## Implementation plan

The tasks below follow the five phases of the build plan; each one ends with a check that tells you it is done.

### Phase 1 · Foundations (days 1–2)

- [x] **Set up the repo.** Monorepo with `backend/` (packages `agent/` with `graph.py`, `nodes/` and `schemas.py`, and `trace_store/`; `pyproject.toml` on uv, `.env.example`, ruff) and `frontend/`. Done when `pytest` runs green on an empty test.
- [x] **Add the ruff pre-commit hook.** Done when a commit with a lint error is refused. `.pre-commit-config.yaml` at the repo root runs `ruff check` and `ruff format --check` on staged backend Python with the ruff in `backend/uv.lock` (`pre-commit` is a dev dependency; install with `cd backend && uv run pre-commit install`). Checked on 2026-11-13: a commit adding an unused import was refused.
- [x] **Move the sketch in and fix serialization.** Models and nodes are split out of the sketch into `agent/`, and state holds plain dicts, so the checkpoint warning is gone. Done when the test run prints no serialization warning.
- [x] **Build the trace collector and store.** A FastAPI endpoint that accepts OTLP over HTTP, decodes it with opentelemetry-proto and writes the traces and spans tables in Postgres; plus the Postgres `TraceReader`, on a read-only role, for the MCP server to use in place of the fixture reader. Done when a test span sent from a script appears in the spans table and comes back through `get_trace_tree`. Built in its simplest form: one `spans` table (no `traces` table), and the reader's session is read-only but the read-only role is not created yet (`tests/test_postgres_reader.py` is the check).
- [x] **Instrument Medas.** One trace per request, with spans for retrieval, each tool call and generation, using the gen\_ai.\* attribute names, exported over OTLP to the collector. Done when a request shows its full span tree in the database. Built in the Medas repo (`medas-api/tracing/`, merged in `Nelev/medas` PR 7). Checked on 2026-11-11 with a real signed-in request: one trace of nine spans (the agent run, three model calls with token usage, three tool calls, two retrievals with their hit counts) arrived in `spans`, was scored, and comes back as a tree through the reader, with no question, answer or record text on any span.
- [ ] **Write the traffic generator.** A YAML file of normal, edge-case and adversarial queries and a script that sends them to Medas. Done when one run produces a mix of passing and failing traces.
- [x] **Build the MCP server and collector node.** A FastMCP server with search\_failed\_traces, get\_trace\_tree and get\_span, read-only, behind a per-run call budget and an audit log, connected to the graph through `langchain-mcp-adapters`, filter by time window, error level and score threshold, map results to `TraceSummary`. It first read a synthetic fixture and now reads Postgres only (the fixture is a test double); the read-only database role comes with the Postgres reader in the collector task above. Done when a unit test on a saved fixture passes.

### Phase 2 · Core agents (days 3–5)

- [x] **Summarise each failure as text.** Failed step, error type, query and score in one short string. Done when summaries for the fixture traces look distinct.
- [x] **Cluster the failures.** Embed the summaries and run HDBSCAN; fall back to grouping by step and error type when there are too few traces. Done when the fixture's known groups come out as separate clusters.
- [x] **Clean the failure text before embedding.** The embedded string (`failure_text`) currently uses the raw error message, so IDs, timestamps and numbers in it can split or merge clusters. Mask them with the same rule as `normalise_error`, keep the error wording and the span context, and check the text carries no clinical content. Done when two traces that differ only in ids, timestamps or numbers produce the same text, and the fixture clusters are unchanged.
- [x] **Write the taxonomy file.** `taxonomy.md` with a definition and one example per category, loaded into the diagnoser prompt. Done when every category has both.
- [x] **Build the diagnoser.** One `with_structured_output(Diagnosis)` call per cluster, with the taxonomy as system prompt and the cluster's exemplar span trees as input; no tools, so no `create_agent`. Retries run in the graph's loop under a per-cluster budget of attempts, tokens and cost. Built and tested with a fake model. Done when it returns a valid `Diagnosis` for each cluster on the real model: first checked on the fixture clusters, now by the eval on a seeded day (`python -m eval.run`).
- [x] **Diagnose unclustered failures individually.** `cluster_failures` turns each id in `unclustered` into a one-trace cluster (`method` `isolated`) numbered after the real clusters, so the existing fan-out, retries and early exit handle it unchanged. No cap yet: add one (and list the skipped ids in the run summary) if a real run shows too many isolated failures. Done when a fixture run with isolated failures returns a diagnosis for each.
- [x] **Validate evidence.** Check that every cited trace id and span exists in the cluster; retry once if not, otherwise lower confidence. Done when a test with a fake citation is caught.
- [ ] **Trace TraceScan itself.** Send its own runs to the same collector under a separate service name. Done when one triage run shows cost and latency per node.
- [x] **Build the scoring job.** Heuristic checks on every trace (empty retrieval, schema errors, timeouts, other tool errors, a failed request), written to the scores table when a trace's root span is stored (`trace_store/scoring.py`); the LLM judge is a stretch goal. The Postgres reader now calls a trace failed when its lowest score is low, not when it has an error span, so a recovered or expected error is left out. Done when every fixture trace has a score: every seeded trace gets at least `request_failed`. Since replaced by the trace judge in the agent (`agent/judge.py`, `nodes/score_trace.py`): the heuristic checks, the scoring at insert and `search_failed_traces` are removed. The judge's verdicts are saved as `scores` rows after each run (`runs/scores.py`), so the trace browser shows them.

### Phase 3 · Loop and eval (days 6–10)

- [x] **Template the proposals.** A markdown issue template (the `_issue` function in `agent/proposals.py`: summary, evidence, suspected cause, fix, verification status) and a regression-case format that fits a regression-cases table in Postgres (`RegressionCase`: ids only, no span text). `draft_proposals` is code, no model call (`agent/proposals.py`), and a cluster without a diagnosis still gets a stub proposal. Done when `draft_proposals` fills both for each cluster.
- [x] **Wire the human review.** `human_review` pauses the run with `interrupt()`. The run stream ends in `review_required`, `GET /v1/runs/{run_id}` returns the status and proposals, and `POST /v1/runs/{run_id}/review` takes approve or reject for every proposal and resumes with `Command(resume=...)`. The runs module (`backend/runs/`) owns all of it. No CLI: the review goes through the API, and the review screen in the UI is a separate task. Done when a run pauses, takes your decisions and continues.
- [ ] **Set up LangGraph Studio.** Add the `local` flag to `build_graph`, a `langgraph.json`, and run `langgraph dev`. Done when you can approve proposals from the Studio UI.
- [x] **Implement dry-run actions.** `apply_actions` writes each approved issue to `out/issues/<cluster>.md` and appends regression cases to `out/regression_cases.jsonl`. `dry_run` comes from the server's `DRY_RUN` setting (on by default, refused when off until the real writers exist). Issue files are named by cluster id only, so a later run replaces an earlier run's file with the same id. Done when a dry run produces those files and nothing else.
- [ ] **Add fault switches to Medas.** One environment variable per fault: empty retrieval for one category, broken tool schema, truncated system prompt, small context window, weaker model, upstream timeouts. Done when each switch reliably causes its failure.
- [ ] **Write the ground-truth file.** For each fault, the expected category, the actual cause and the visible symptom, plus several input sets that trigger it. Done when all six faults are listed with at least two input sets each, including at least one pair of faults whose error messages look alike (for example the upstream timeout and the retrieval failure) and one low-volume fault that should land in `unclustered`.
- [ ] **Build the eval runner.** For each fault and input set: switch it on, run traffic, run triage, save the proposals, switch it off; plus healthy control runs with no fault. Done when one command runs all faults and controls.
- [ ] **Compute the metrics.** Detection rate, root-cause accuracy (cause, not symptom), cluster purity and cause separation, rare-failure recall, false alarms on healthy runs, cost and time per run, written to a results table. Done when the table is in the README. On seeded traces this is built: `eval.metrics` scores all of these plus the trace judge, a control day (`eval.run --control`) gives the false alarms on healthy traffic, and the README has the table (experiment 5 in `docs/eval-notes.md`). Still open: the same on Medas's own fault switches, if the seeded eval does not stand in for them.
- [ ] **Check the clustering against the faults.** On the fault-injection runs, count faults split across clusters and clusters that mix faults, and check which cluster or `unclustered` entry each injected fault ends up in. Done when the result is in the README; change the model, thresholds or text only if it shows a problem, and re-run to confirm.
- [ ] **MVP gate check.** Every MVP task above is ticked and the metrics table is filled. If not, cut stretch tasks before moving on.

### Phase 4 · Stretch (days 11–14)

Do these in order and stop where time runs out; each one is useful on its own.

- [ ] **Build the reproducer.** Run Medas in Docker, replay each cluster's exemplar inputs three times, and set confirmed, flaky or unconfirmed. Failures that do not reproduce stay in the proposal as unconfirmed, which matters for intermittent timeouts. A reproduced failure confirms the symptom, not the proposed root cause, so the diagnosis keeps its own confidence. Done when an injected fault shows as confirmed and an intermittent timeout shows as flaky or unconfirmed instead of disappearing.
- [ ] **Add known-issues memory.** Index cluster signatures in the store with embeddings and match by semantic search above a threshold. Done when a second run on the same fault updates the existing issue instead of creating a new one.
- [x] **Connect GitHub.** A fine-grained token scoped to a test repo; create issues and add comments for updates. Done when an approved proposal opens a real issue in the test repo. Issues are created (`agent/github.py`, githubkit, a private repo checked at startup, a hidden marker so a retried review opens no duplicate) and were checked against a real test repo; comments for updates wait for the known-issues memory, which is what knows an issue already exists.
- [ ] **Run the MAST-Data study.** Write an adapter from MAST-Data traces to `TraceSummary`, run the diagnoser on the 21 MAST-Data-human traces, and compute accuracy and Cohen's kappa. Done when the numbers are in the results table next to the paper's.

**Review UI (Next.js).** Built ahead of the stretch phase as one run-console page; the run detail and results pages are not scheduled yet.

- [x] **Scaffold the app.** Next.js with the App Router and TypeScript in `frontend/`: a single run-console page that streams a run from the FastAPI backend through a `/api` rewrite. It does not use `@langchain/langgraph-sdk` or a LangGraph server, and holds no server keys. Done when the home page lists existing runs (each run is a graph thread).
- [x] **Runs page.** Each triage run with its window, status (running, waiting for review, done, failed, aborted) and number of clusters. It is the Runs tab of the run console (`frontend/app/_components/runs-table.tsx`), over `GET /v1/runs`. Done when a new run appears without a restart.
- [x] **Run detail page.** Clusters with trace counts, each diagnosis with category, confidence and cited spans linked to the trace in the trace viewer, plus verification status. Done when every field in the state shows up somewhere. It is the Run tab of the run console (`frontend/app/_components/run-pane.tsx`), over `GET /v1/runs/{run_id}/detail`, with the pipeline drawn node by node; the proposals' text and the actions log stay under Review, and `reproductions` and `known_matches` have no node yet (drawn as Not built). Checked on 2026-11-11 on a real run of 50 failed traces in 8 clusters.
- [x] **Review screen.** Approve or reject per proposal, then resume the paused thread with the decisions. It is the Review tab of the run console (`frontend/app/_components/review-pane.tsx`), over `GET /v1/runs/{run_id}` and `POST /v1/runs/{run_id}/review`. Done when approving in the UI produces the same actions as the review API (there is no CLI).
- [ ] **Results page.** The fault-injection metrics table and a chart per metric. Done when it reads the saved eval results file.
- [ ] **Replace the CLI in the demo.** Record the review step in the UI instead of the terminal. Done when the demo video shows the dashboard.
- [x] **Trace viewer (part of the MVP).** A plain trace list and a span-tree view of one trace, nothing more, read from the trace store. It is the Traces tab of the run console (`frontend/app/_components/traces-pane.tsx`), over `GET /v1/traces` and `GET /v1/traces/{trace_id}` (`backend/api/trace_browser.py`, read-only, attributes sanitized like the MCP server's). Done when a failing Medas trace can be inspected without Jaeger: checked on 2026-11-11 with the real Medas trace and a failed tool-schema trace.

**UI redesign (planned 2026-11-11, built on `feat/ui-redesign`).** The run console puts six tabs side by side: no run can be linked, the agent's progress is only a message stream, a diagnosis and the spans it cites sit on different tabs, and review is a tab of its own. The redesign replaces the tabs with routes and a slim left nav, makes the run page the place that shows what the agent is doing, and keeps the json-render console as a side rail. It stays on the current design system (navy surfaces, one blue accent, `warning` only for "waiting on you"). Do the tasks in order; each is usable on its own.

- [x] **Shell and routes.** A left nav and three routes: `/` (runs), `/runs/[id]` (one run, live or finished), `/traces` and `/traces/[id]`. "New run" becomes a header button opening a small dialog (app, window) that lands on `/runs/[id]` once `run_started` names the run; the form no longer sits on top of every page. The existing panes move into the routes with no new features. Done when a run and a trace can be opened from a pasted URL and the browser's back button returns to the list. Checked on 2026-11-11.
- [x] **Run page.** A header (run id, status chip with elapsed time, app, window, spend, Cancel while running) over a pipeline stepper: Collect → Judge → Cluster → Diagnose → Draft → Review → Apply, each step with its state and count (traces, failed, clusters, diagnosed `n/N`), driven live by the progress events (`node_progress` quarters for the judge) and filled from `GET /v1/runs/{run_id}/detail` afterwards. Below it, a findings column of one card per cluster (Queued, Diagnosing…, then signature, category, confidence, evidence check, root cause, spend), reloaded from the detail endpoint after each finished node, and the json-render console as a right-hand rail ("Agent console"), with Raw events as a toggle in its header instead of a tab. Done when a live run shows its current step and the cluster cards fill in without a page reload, and a finished run reads the same from its URL. Checked on 2026-11-13 on a live run of Medas's last 24 hours (75 traces, 7 failed, 1 cluster): the stepper moved stage by stage and the card went from Diagnosing to its diagnosis without a reload, and after a backend restart the run read the same from its URL.
- [x] **Trace tree component.** One `TraceTree`: an indented span tree combined with a waterfall on the root's timeline, an icon per span kind (agent, chat, tool, retrieval), error spans in red, the blamed span and the spans a diagnosis cites marked, and a drawer with the picked span's sanitized attributes and events. Used both inline in an expanded cluster card (its exemplar traces, "2 of 3" to step through them) and on `/traces/[id]`. No new endpoint: `GET /v1/traces/{trace_id}` already returns the sanitized tree. Done when every cited span of a diagnosis can be seen in its tree from the cluster card without leaving the run page. Checked on 2026-11-11 on a run of 8 clusters.
- [x] **Inline review and runs overview.** Approve or Reject on each cluster card, "View issue" opening the drafted issue in a drawer, and a sticky bar ("n of N decided · Submit decisions") that sends one `POST /v1/runs/{run_id}/review`; then the Review and Raw events tabs are retired. The runs page gets a "Needs your review" strip (the only call to action), four tiles (runs in the last 7 days, failures found, open proposals, spend) and a table with a small funnel per run (traces → failed → clusters → proposals), duration and spend. Backend gaps: `RunRecord` has no duration or spend (`ended_at` exists; spend needs summing per run) and the run's spend leaves out the trace judge's. Done when a waiting run can be found from the home page and reviewed without opening another tab. Checked on 2026-11-13: a waiting run was rejected from its run page with the bar, the run completed and the review was recorded. The backend gaps above (duration, spend per run, the judge's spend) are still open.
- [x] **Dashboard.** A landing page at `/` (the runs table moves to `/runs`) with what helps a reader decide where to look: the review backlog, the latest failure rate, failed traces of the week, open proposals and the oldest wait, failed traces by category and the largest clusters of the newest analyzed run, failed traces per run over time, the week's run outcomes, and the latest diagnosis spend. Read from the run list and one run detail; no new endpoint. Done when it shows all of these for real runs: checked on 2026-11-11. Later, with backend support: trends by category across runs (needs per-run categories in the list), the judge's spend, and approve/reject rates per category (needs the reviews in an endpoint).

### Phase 5 · Ship (days 15–16)

- [x] **Switch to Postgres.** Postgres checkpointer and store instead of the in-memory versions. The checkpointer is done (`AsyncPostgresSaver` in `main.py`); the store is still `InMemoryStore` (the healthy spans and scores have their own Postgres tables). Done when a paused run survives a restart: checked on 2026-11-13, a run waiting for review was reviewed through a restarted backend and completed.
- [x] **Record runs, users and reviews.** Three tables next to the checkpoints (`users`, `runs`, `reviews`), created by Alembic migrations, and a run store the runs module writes to: who started a run, how it ended (`failed` and `aborted` included), who decided what. Users are recorded by name from a header; there is no login. `GET /v1/runs` lists the runs. Done when the run store tests pass against Postgres (`TEST_DATABASE_URL`) and the app refuses to start before the migration has run.
- [x] **Sign in with Clerk.** A TraceScan application in Clerk of its own (not Medas's), sign-up restricted to invited accounts, `name` and `email` added to the session token. Backend: every route but `/health` and the collector verifies a Clerk session token (`backend/auth/`), and runs and reviews are recorded under the token's name, not the `X-User-Name` header (built). Frontend: `ClerkProvider`, a `proxy.ts` that sends signed-out pages to `/sign-in`, `<UserButton/>` in the header, and `lib/api.ts` sending `Authorization: Bearer` from `getToken()` on every call, the run stream included (built). The collector has its own credential (`COLLECTOR_TOKEN_MEDAS`). Still open: the Clerk user id stored next to each name (`started_by_id`, `reviewer_id`). Done when a signed-out browser lands on `/sign-in`, a signed-in one can start and review a run recorded under its name, and a request with no token gets a `401`: checked on 2026-11-13. Running Medas's UI on localhost:3000 in the same browser can leave TraceScan's Clerk cookies stale (a redirect loop on `/sign-in`); clearing the `__session_*`, `__client_uat_*` and `__clerk_db_jwt_*` cookies with TraceScan's suffix fixes it.
- [ ] **Deploy.** Docker Compose with Medas, TraceScan, the trace collector and Postgres. Done when a triage run works on the deployed version.
- [ ] **Schedule a daily run.** A cron job that triages the last 24 hours and waits for review. Done when one scheduled run has produced proposals.
- [ ] **Write the README.** Problem, architecture diagram, how to run, eval results, limitations. Done when someone new could run the demo from it.
- [ ] **Record the demo.** Three minutes: switch on a fault, run traffic, run triage, approve, show the issue. Done when the video is linked in the README.
- [ ] **Keep half a day as buffer.** For whatever slipped earlier.

## Risks and open questions

The biggest risk is not the agent logic but producing enough realistic failing traffic to triage.

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Too little realistic failing traffic | Clusters are trivial and the eval says little | Build the traffic script on day 1–2; mix normal, edge-case and adversarial queries |
| Feels like infrastructure, not a product | Weaker demo for reviewers | Three-minute demo: inject a bug, run triage, approve, issue appears |
| Building the tracing stack takes time | About 3–4 days less for stretch goals | Keep the store to three tables and the MCP server to three tools; real GitHub issues and MAST-Data stay stretch only |
| Diagnoser overconfident on vague clusters | False positives filed | Require cited evidence; show verification status and confidence on every proposal; grade root cause, not symptom, in the eval |
| Pydantic objects in checkpoints | LangGraph warns and will block later | Solved: state stores plain dicts. Keep it that way for new fields |
| Proposal text echoes clinical content | The diagnoser sees span attributes, and its prose (cause, fix, evidence notes) goes into the issue body | Regression cases and evidence carry ids only; the run stream sends each proposal, issue text included, to the browser of whoever runs the triage and nothing logs it; dry run by default and the human review gate come before any write; real issues go only to a private repo (checked at startup). A PII scan of proposal text is still not built |
| LLM cost of triage runs | Budget overrun during eval | Clustering in code; LLM calls only per cluster, not per trace; the one exception, unclustered failures, is not capped yet (add a per-run cap if a real run shows too many); each cluster has a budget of attempts, tokens and cost |
| Look-alike failures merge, or one cause splits | Wrong or duplicate diagnoses | Embed a cleaned summary; check purity and cause separation against the injected faults before adding any complexity |
| Rare failures lost as noise | A real issue never reaches the reviewer | Keep `unclustered` and diagnose each one |

Decided: no third-party observability platform. Medas is instrumented with OpenTelemetry and sends its traces to TraceScan's own collector and Postgres store, so the project owns the full path from trace to fix. A local Jaeger container may be used in the first days to inspect traces before the own viewer exists.

Open questions:

- Is the CoA agent a second target app, or kept out of scope?
- Does the course require a deployed demo, or is a recorded one enough?
