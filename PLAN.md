<!--
Claude Code: this is the project plan for TraceScan (capstone, AI Engineering course).
Use it as the source of truth for scope and task order:
- Work through "Implementation plan" phase by phase; tick a task's checkbox when its "Done when" check passes.
- Keep the MVP tight. Do not start stretch tasks before the MVP gate check passes.
- MVP proposals are "unverified"; never drop a cluster because it did not reproduce.
- Trace access is read-only (MCP server on a read-only DB role). All writes happen only in apply_actions, after human approval, with dry_run on by default.
- The starting point is the graph sketch tracedoctor_graph.py (rename into the tracescan/ package).
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
                                    diagnose_cluster  x N (create_agent per cluster and per unclustered failure, in parallel; read-only trace tools)
                                    [join]                (waits for all diagnoses)
Medas sandbox  <--replay--          reproduce_failure x N (stretch: replays inputs; MVP marks every diagnosis "unverified")
Known-issues store --lookup-->      match_known_issues    (links clusters to issues from earlier runs)
                                    draft_proposals       (create or update issue; shows verification status)
                                    human_review          (interrupt(); ends if nothing is approved)
GitHub + eval dataset <--write--    apply_actions         (approved items only; dry run by default; also updates the store)
                                    END
```

Stacked boxes run once per item in parallel: one diagnosis per cluster and one per unclustered failure (capped, see Clustering), one replay per diagnosis. A no-op join node (not drawn) waits for every diagnosis before reproduction starts. The run ends early if there are no failures at all (no clusters and nothing unclustered) or if the reviewer approves nothing. In the MVP the reproduce step only marks each diagnosis as unverified; replay against Medas is a stretch goal.

Inside the graph, `diagnose_cluster` is a small agent of its own, built with LangChain's `create_agent`. It can call the read-only trace tools to inspect a failing trace's full span tree, single spans or similar traces before it answers, and returns a `Diagnosis` through `response_format`. A low recursion limit caps its steps. The outer pipeline stays a plain `StateGraph`, so order, parallelism, batch approval and evaluation remain fixed.

## State and data model

One shared state object flows through the graph; the two fields filled by parallel branches use an append reducer so results are merged, not overwritten.

| Field | Type | Written by | Notes |
| --- | --- | --- | --- |
| `target_app`, `since` | str | input | Which app and time window to triage |
| `failed_traces` | list\[TraceSummary\] | collect\_traces | Compact view of each failed or low-score trace |
| `clusters` | list\[Cluster\] | cluster\_failures | Groups with a signature and a few exemplar traces |
| `unclustered` | list\[str\] | cluster\_failures | Ids of isolated failures; each is also a one-trace cluster (`method` `isolated`) and is diagnosed on its own |
| `diagnoses` | list\[Diagnosis\], append reducer | diagnose\_cluster (parallel) | Category, root cause, fix, confidence, evidence spans |
| `diagnosis_failures` | list\[str\], append reducer | diagnose\_cluster (parallel) | Ids of clusters whose diagnosis failed; reported, not dropped |
| `reproductions` | list\[Reproduction\], append reducer | reproduce\_failure (parallel) | Unverified in the MVP; with replay, confirmed, flaky or unconfirmed |
| `known_matches` | dict cluster → issue id | match\_known\_issues | Links to issues from earlier runs |
| `proposals` | list\[Proposal\] | draft\_proposals | Create or update issue, body, regression case |
| `decisions` | dict cluster → approve/reject | human\_review | Supplied by the reviewer on resume |
| `actions_log` | list\[str\], append reducer | apply\_actions | What was written, or would be in dry run |

Parallel branches do not receive the whole state. Each diagnose branch gets a small `ClusterTask` (target app plus one cluster) and each reproduce branch a `ReproTask` (cluster plus its diagnosis), which keeps prompts short.

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
| TraceScan MCP server over the trace store (search traces, get trace tree, get span) | Read | collect\_traces, diagnose\_cluster (agent) | Read-only database role |
| Target app API in a sandbox | Execute | reproduce\_failure | Replays exemplar inputs only, N attempts each |
| GitHub issues (create, comment) | Write | apply\_actions | Approved proposals only |
| Eval dataset (add regression case) | Write | apply\_actions | Approved proposals only |
| Known-issues store | Write | apply\_actions | Updated after an approved action |

The trace reader is a small MCP server built with FastMCP on top of the trace store. It offers three tools (`search_failed_traces`, `get_trace_tree`, `get_span`) and connects to Postgres with a read-only database role, so it cannot change data whatever the agent asks. Both the collector node and the diagnoser agent use it.

The human gate is LangGraph's `interrupt()` in the `human_review` node. The graph pauses with the list of proposals, the reviewer resumes it with an approve or reject per cluster, and only approved items reach `apply_actions`. If nothing is approved, the graph ends without writing anything.

A `dry_run` flag in the run config makes `apply_actions` log what it would do instead of calling GitHub. It is on by default and used for demos and eval runs.

## Tracing stack

Instead of an observability platform, TraceScan comes with its own small tracing stack built on OpenTelemetry, the vendor-neutral standard for traces.

```text
Medas (OTel SDK, gen_ai.* attributes) --OTLP/HTTP--> Trace collector (FastAPI, POST /v1/traces)
                                                            | spans
                                                            v
Scoring job (heuristics; LLM judge = stretch) <--> Postgres trace store (traces, spans, scores tables)
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
| Trace collector | Receives OTLP over HTTP, decodes it and writes traces and spans | FastAPI, `opentelemetry-proto` |
| Trace store | Three tables: traces (id, timing, status), spans (ids, parent id, name, kind, timing, status, attributes and events as JSONB), scores (trace, evaluator, value, comment) | Postgres, the same instance as checkpoints and memory |
| Scoring job | Marks bad answers that raised no error: heuristic checks on every trace (MVP), and as a stretch an LLM judge for groundedness on every failure and a 10% sample of successes | Python worker, structured output |
| MCP server | `search_failed_traces`, `get_trace_tree`, `get_span` for the agent | FastMCP, read-only database role |
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
| Review UI | Next.js (App Router, TypeScript) + LangGraph JS SDK | Runs list, run detail, approve or reject proposals, eval results |
| Diagnoser agent | LangChain create\_agent with response\_format | Investigates each cluster with the read-only trace tools |

To run the sketch locally: install LangGraph in a virtual environment and run `python tracedoctor_graph.py` (the file can be renamed). The script runs until the review pause, prints the proposals, then resumes with decisions; the same `thread_id` links the two calls.

To run it in LangGraph Studio: compile the graph without a local checkpointer and store (the server provides persistence), point `langgraph.json` at the module's `graph` variable, and start `langgraph dev`. Studio then shows the graph and offers the resume step at the human review node.

## Scope and build plan

The MVP shows one path end to end: failed traces in, evidence-backed issue proposals out, measured by the fault-injection eval, done by day 10 of 16. The collector, store and viewer stay as small as that path needs; everything else is optional.

**MVP (must ship)**

- [ ] Medas traced with OpenTelemetry into the own trace store, plus a script that generates realistic and adversarial traffic
- [ ] Minimal trace collector, Postgres store, heuristic scoring and read-only MCP server
- [ ] Clustering of failures with embeddings and HDBSCAN, isolated failures kept for individual diagnosis
- [ ] Diagnoser with structured output and the failure taxonomy
- [ ] Human review gate with approve or reject per proposal
- [ ] Draft issues written to markdown files (dry run)
- [ ] Fault-injection eval with six seeded bugs, varied inputs, healthy control runs and the metrics table; proposals marked unverified
- [ ] Minimal trace viewer in Next.js: plain trace list and span tree

**Stretch (if time allows)**

- [ ] Replay-based reproducer in a sandbox
- [ ] Known-issues memory with semantic matching
- [ ] Real GitHub issue creation
- [ ] MAST-Data agreement study
- [ ] Scheduled daily triage run and a deployed demo
- [ ] Next.js review dashboard in front of the LangGraph server
- [ ] LLM judge for groundedness in the scoring job

The phases below are in working days, since no start date is fixed yet.

| Phase | Days | Focus | MVP? |
| --- | --- | --- | --- |
| Foundations | 1–2 | Repo, trace collector and store, Medas instrumentation, traffic script, MCP server | Yes |
| Core agents | 3–5 | Clustering, taxonomy, diagnoser agent, evidence check, scoring job | Yes |
| Loop and eval | 6–10 | Proposals, human review, dry-run actions, fault injection with controls, metrics | Yes |
| **Gate: MVP complete, day 10** | | Six faults run, controls run, metrics table filled | |
| Stretch | 11–14 | Reproducer, known-issues memory, GitHub, MAST-Data, review UI | No |
| Ship | 15–16 | Postgres persistence, deploy, README, demo video, buffer | Yes |

The first three phases make up the MVP; if the gate slips, the stretch phase shrinks first and the ship phase is protected.

## Implementation plan

The tasks below follow the five phases of the build plan; each one ends with a check that tells you it is done.

### Phase 1 · Foundations (days 1–2)

- [ ] **Set up the repo.** Package layout `tracescan/` with `graph.py`, `nodes/`, `tools/`, `models.py`, `evals/`; `pyproject.toml`, `.env.example`, pre-commit with ruff. Done when `pytest` runs green on an empty test.
- [ ] **Move the sketch in and fix serialization.** Split models and nodes out of the sketch; store plain dicts in state (or register the models module) so the checkpoint warning disappears. Done when the demo run prints no warnings.
- [ ] **Build the trace collector and store.** A FastAPI endpoint that accepts OTLP over HTTP, decodes it with opentelemetry-proto and writes the traces and spans tables in Postgres. Done when a test span sent from a script appears in the spans table.
- [ ] **Instrument Medas.** One trace per request, with spans for retrieval, each tool call and generation, using the gen\_ai.\* attribute names, exported over OTLP to the collector. Done when a request shows its full span tree in the database.
- [ ] **Write the traffic generator.** A YAML file of normal, edge-case and adversarial queries and a script that sends them to Medas. Done when one run produces a mix of passing and failing traces.
- [ ] **Build the MCP server and collector node.** A FastMCP server with search\_failed\_traces, get\_trace\_tree and get\_span on a read-only database role, connected to the graph through `langchain-mcp-adapters`, filter by time window, error level and score threshold, map results to `TraceSummary`. Done when a unit test on a saved fixture passes.

### Phase 2 · Core agents (days 3–5)

- [x] **Summarise each failure as text.** Failed step, error type, query and score in one short string. Done when summaries for the fixture traces look distinct.
- [x] **Cluster the failures.** Embed the summaries and run HDBSCAN; fall back to grouping by step and error type when there are too few traces. Done when the fixture's known groups come out as separate clusters.
- [x] **Clean the failure text before embedding.** The embedded string (`failure_text`) currently uses the raw error message, so IDs, timestamps and numbers in it can split or merge clusters. Mask them with the same rule as `normalise_error`, keep the error wording and the span context, and check the text carries no clinical content. Done when two traces that differ only in ids, timestamps or numbers produce the same text, and the fixture clusters are unchanged.
- [x] **Write the taxonomy file.** `taxonomy.md` with a definition and one example per category, loaded into the diagnoser prompt. Done when every category has both.
- [ ] **Build the diagnoser.** A create\_agent with the taxonomy as system prompt, the read-only trace tools, the cluster's exemplar spans as input, response\_format=Diagnosis and a recursion limit of about 12, instead of a single call through `with_structured_output(Diagnosis)`. Done when it returns a valid `Diagnosis` for each fixture cluster.
- [x] **Diagnose unclustered failures individually.** `cluster_failures` turns each id in `unclustered` into a one-trace cluster (`method` `isolated`) numbered after the real clusters, so the existing fan-out, retries and early exit handle it unchanged. No cap yet: add one (and list the skipped ids in the run summary) if a real run shows too many isolated failures. Done when a fixture run with isolated failures returns a diagnosis for each.
- [x] **Validate evidence.** Check that every cited trace id and span exists in the cluster; retry once if not, otherwise lower confidence. Done when a test with a fake citation is caught.
- [ ] **Trace TraceScan itself.** Send its own runs to the same collector under a separate service name. Done when one triage run shows cost and latency per node.
- [ ] **Build the scoring job.** Heuristic checks on every trace (empty retrieval, schema errors, timeouts), written to the scores table; the LLM judge is a stretch goal. Done when every fixture trace has a score.

### Phase 3 · Loop and eval (days 6–10)

- [x] **Template the proposals.** A markdown issue template (the `_issue` function in `agent/proposals.py`: summary, evidence, suspected cause, fix, verification status) and a regression-case format that fits a regression-cases table in Postgres (`RegressionCase`: ids only, no span text). `draft_proposals` is code, no model call (`agent/proposals.py`), and a cluster without a diagnosis still gets a stub proposal. Done when `draft_proposals` fills both for each cluster.
- [ ] **Wire the human review.** A small CLI that shows each proposal and asks approve or reject, then resumes with `Command(resume=...)`. Done when a run pauses, takes your input and continues.
- [ ] **Set up LangGraph Studio.** Add the `local` flag to `build_graph`, a `langgraph.json`, and run `langgraph dev`. Done when you can approve proposals from the Studio UI.
- [ ] **Implement dry-run actions.** `apply_actions` writes each approved issue to `out/issues/<cluster>.md` and appends regression cases to a local JSONL file. Done when a dry run produces those files and nothing else.
- [ ] **Add fault switches to Medas.** One environment variable per fault: empty retrieval for one category, broken tool schema, truncated system prompt, small context window, weaker model, upstream timeouts. Done when each switch reliably causes its failure.
- [ ] **Write the ground-truth file.** For each fault, the expected category, the actual cause and the visible symptom, plus several input sets that trigger it. Done when all six faults are listed with at least two input sets each, including at least one pair of faults whose error messages look alike (for example the upstream timeout and the retrieval failure) and one low-volume fault that should land in `unclustered`.
- [ ] **Build the eval runner.** For each fault and input set: switch it on, run traffic, run triage, save the proposals, switch it off; plus healthy control runs with no fault. Done when one command runs all faults and controls.
- [ ] **Compute the metrics.** Detection rate, root-cause accuracy (cause, not symptom), cluster purity and cause separation, rare-failure recall, false alarms on healthy runs, cost and time per run, written to a results table. Done when the table is in the README.
- [ ] **Check the clustering against the faults.** On the fault-injection runs, count faults split across clusters and clusters that mix faults, and check which cluster or `unclustered` entry each injected fault ends up in. Done when the result is in the README; change the model, thresholds or text only if it shows a problem, and re-run to confirm.
- [ ] **MVP gate check.** Every MVP task above is ticked and the metrics table is filled. If not, cut stretch tasks before moving on.

### Phase 4 · Stretch (days 11–14)

Do these in order and stop where time runs out; each one is useful on its own.

- [ ] **Build the reproducer.** Run Medas in Docker, replay each cluster's exemplar inputs three times, and set confirmed, flaky or unconfirmed. Failures that do not reproduce stay in the proposal as unconfirmed, which matters for intermittent timeouts. A reproduced failure confirms the symptom, not the proposed root cause, so the diagnosis keeps its own confidence. Done when an injected fault shows as confirmed and an intermittent timeout shows as flaky or unconfirmed instead of disappearing.
- [ ] **Add known-issues memory.** Index cluster signatures in the store with embeddings and match by semantic search above a threshold. Done when a second run on the same fault updates the existing issue instead of creating a new one.
- [ ] **Connect GitHub.** A fine-grained token scoped to a test repo; create issues and add comments for updates. Done when an approved proposal opens a real issue in the test repo.
- [ ] **Run the MAST-Data study.** Write an adapter from MAST-Data traces to `TraceSummary`, run the diagnoser on the 21 MAST-Data-human traces, and compute accuracy and Cohen's kappa. Done when the numbers are in the results table next to the paper's.

**Review UI (Next.js).** Not yet scheduled: about 2–3 days, which would come out of the tasks above.

- [ ] **Scaffold the app.** Next.js with the App Router and TypeScript in `ui/`, talking to the LangGraph server through `@langchain/langgraph-sdk`; server keys stay in server-side route handlers. Done when the home page lists existing threads.
- [ ] **Runs page.** Each triage run with its window, status (running, waiting for review, done) and number of clusters. Done when a new run appears without a restart.
- [ ] **Run detail page.** Clusters with trace counts, each diagnosis with category, confidence and cited spans linked to the trace in the trace viewer, plus verification status. Done when every field in the state shows up somewhere.
- [ ] **Review screen.** Approve or reject per proposal, then resume the paused thread with the decisions. Done when approving in the UI produces the same actions as the CLI.
- [ ] **Results page.** The fault-injection metrics table and a chart per metric. Done when it reads the saved eval results file.
- [ ] **Replace the CLI in the demo.** Record the review step in the UI instead of the terminal. Done when the demo video shows the dashboard.
- [ ] **Trace viewer (part of the MVP).** A plain trace list and a span-tree view of one trace, nothing more, read from the trace store. Done when a failing Medas trace can be inspected without Jaeger.

### Phase 5 · Ship (days 15–16)

- [ ] **Switch to Postgres.** Postgres checkpointer and store instead of the in-memory versions. Done when a paused run survives a restart.
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
| Pydantic objects in checkpoints | LangGraph warns now and will block later | Register the models module with the serializer, or store plain dicts |
| Proposal text echoes clinical content | The diagnoser sees span attributes, and its prose (cause, fix, evidence notes) goes into the issue body | Regression cases and evidence carry ids only; dry run by default and the human review gate come before any write; add a PII scan of proposal text before real GitHub issues |
| LLM cost of triage runs | Budget overrun during eval | Clustering in code; LLM calls only per cluster, not per trace; the one exception, unclustered failures, is capped per run |
| Look-alike failures merge, or one cause splits | Wrong or duplicate diagnoses | Embed a cleaned summary; check purity and cause separation against the injected faults before adding any complexity |
| Rare failures lost as noise | A real issue never reaches the reviewer | Keep `unclustered` and diagnose each one |

Decided: no third-party observability platform. Medas is instrumented with OpenTelemetry and sends its traces to TraceScan's own collector and Postgres store, so the project owns the full path from trace to fix. A local Jaeger container may be used in the first days to inspect traces before the own viewer exists.

Open questions:

- Is the CoA agent a second target app, or kept out of scope?
- Does the course require a deployed demo, or is a recorded one enough?
