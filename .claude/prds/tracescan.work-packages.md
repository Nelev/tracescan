# TraceScan work packages

> Derived from `tracescan.prd.md` and the architecture overview. Split into features that independent subagents can build in parallel. Paths are proposed, not decided. The Medas repository location is TBD.

## How parallel work stays independent

1. **Contracts first.** The Contracts and fixtures feature produces the API, tool and model contracts plus synthetic fixture traces. Every parallel feature builds and tests against those, never against another feature's code.
2. **One owner per path.** A feature edits only the paths it owns. Anything else goes through the lead.
3. **Stubs and mocks stand in for neighbours.** Examples: `m1` mocks the trace API, `a1` stubs the MCP client, `c5` seeds Postgres with fixtures.
4. **Contracts do not change inside a feature.** If a contract is wrong, report it; the lead changes it and tells the affected features.
5. **Joins are separate cards.** The MVP integration feature connects real parts after the parallel work lands.

### Standard brief for each subagent

> You own the feature **{name}** in `tracescan.work-packages.md`. Read `contracts/` and `fixtures/` first. Build only the cards listed for your feature, in dependency order. Edit only the paths you own. Use the stubs and mocks named in the cards instead of other features' code. Your tests must pass with fixtures alone. Finish by reporting the files you changed, which cards are done, and any contract problem you found. Do not change contracts yourself.

## Waves

A wave can start when the features in earlier waves have landed (decisions excluded). Features in the same wave can run at the same time.

| Wave | Features | Parallel agents |
|---|---|---|
| Decide first | Project decisions | 0 (author) |
| 1 | Contracts and fixtures | 1 |
| 2 | Trace collector and API; Medas instrumentation and fault injection; Read-only MCP server; Trace viewer UI; Triage analysis nodes; Human review and dry-run actions; Eval ground truth and metrics | 7 |
| 3 | MVP integration and eval run; MAST-Data benchmark (stretch) | 1 |
| 4 | Baseline, thresholds and MVP gate | 0 |
| 5 | Replay reproduction (stretch); Known-issues memory (stretch); Review dashboard (stretch); Deploy, README and demo (ship) | 4 |
| 6 | GitHub issues (stretch); Stretch evaluation rerun (stretch) | 2 |

`*` after a card id below marks a dependency on another feature.

## Features

### Project decisions

- **Wave:** decide first · **Tier:** MVP
- **Owns:** The author, not an agent
- **Goal:** The four open questions from the PRD. Answer these first; they unblock or shape other work.
- **Builds against:** nothing outside this feature
- **Done when:** Each question has a written answer recorded in the PRD.

| Card | Area | Task | Needs |
|---|---|---|---|
| d1 | shared | Confirm building a custom tracing stack instead of using a platform such as Langfuse (Open question in the PRD. Settle before tracing work starts.) | — |
| d2 | shared | Decide how sensitive clinical content in Medas traces is stored and shared (Medas is clinician-facing. Affects storage and what may go into GitHub issues.) | — |
| d4 | shared | Decide whether the MAST-Data comparison joins the MVP (Open question in the PRD: is fault injection enough on its own?) | — |
| d3 | shared | Confirm whether the course needs a deployed demo or a recorded one | — |

#### Card details: Project decisions

**d1. Confirm building a custom tracing stack instead of using a platform such as Langfuse**

The PRD asks whether building a custom tracing stack (collector, store, viewer) is a good use of capstone time compared with a platform such as Langfuse. The architecture assumes custom, so this answer sets the size of milestone 1.

- Compare the effort of the collector, scoring and viewer with adopting a platform and reading traces from its API
- Check whether the course expects you to build the tracing path yourself
- Write the answer and the reason under Open Questions in the PRD
- **Done when:** The decision is written in the PRD. If the answer is not custom, the collector, trace API and viewer cards need to be reworked.
- **Open point:** Open question in the PRD. Settle before tracing work starts.

**d2. Decide how sensitive clinical content in Medas traces is stored and shared**

Medas is clinician-facing, so its traces may hold clinical content. The decision sets what is stored, what is redacted and what may appear in a GitHub issue.

- Find out whether Medas questions, retrieved passages or answers can contain patient data
- Pick one approach: store metadata only, redact before storing, or store everything in a private database
- Decide what the issue body and regression test may quote
- Write the decision in the PRD
- **Done when:** A written rule exists that the collector (b5), Medas instrumentation (b6) and issue drafting (b30) can follow.
- **Open point:** Medas is clinician-facing. Affects storage and what may go into GitHub issues.

**d4. Decide whether the MAST-Data comparison joins the MVP**

The PRD asks whether fault injection alone is a strong enough evaluation, since the author injects the bugs and also built the agent. Adding the MAST-Data comparison brings in an outside benchmark.

- Weigh fault injection alone against adding a published benchmark
- Estimate the effort of cards b71 to b74 against the day 10 deadline
- Record yes or no in the PRD
- **Done when:** A yes or no is recorded. If yes, the MAST-Data cards move into milestone 4.
- **Open point:** Open question in the PRD: is fault injection enough on its own?

**d3. Confirm whether the course needs a deployed demo or a recorded one**

The course may require a live deployed demo or accept a recorded one. The answer decides whether the two deploy cards are needed.

- Check the course brief or ask the instructor
- If a recording is enough, the deploy cards b78 and f15 are skipped
- Record the answer in the PRD
- **Done when:** The demo format is recorded in the PRD.

### Contracts and fixtures

- **Wave:** 1 · **Tier:** MVP
- **Owns:** contracts/, fixtures/
- **Goal:** Shared schemas, API and tool contracts, shared models and synthetic fixture data. Every other feature builds against these instead of waiting on another feature.
- **Builds against:** Project decisions (d1)
- **Done when:** Contracts and fixtures exist, and each parallel feature can run its tests with no other feature present.

| Card | Area | Task | Needs |
|---|---|---|---|
| b1 | backend | Create Postgres tables for traces and spans | d1* |
| b2 | backend | Create the scores table linked to traces | b1 |
| b20 | backend | Define the fixed failure taxonomy (Category list is not defined in the source document.) | — |
| b21 | backend | Pydantic model for a diagnosis: category, cause, suggested fix, spans | b20 |
| c7 | backend | Define span attribute names for retrieval, model-call, tool-call and error spans (Medas writes these, the collector stores them, the agent reads them.) | b1 |
| c1 | backend | Write the trace API contract for list and detail (OpenAPI) | b1, b2 |
| c2 | backend | Write the MCP tool contract: tool names, inputs and outputs | b1, b2 |
| c3 | backend | Define shared models: graph state, proposal, review decision and run summary | b21 |
| c4 | backend | Create fixture traces: a few synthetic failed traces per fault, in the stored format (Lets every other feature work without the real collector or Medas.) | b1, b2, b20 |
| c5 | backend | Seed script: load the fixture traces into Postgres | c4 |
| c6 | backend | Create fixture proposals and review decisions for testing review and actions | c3, c4 |
| b22 | backend | Triage graph skeleton: shared state and a run entry point taking a time window | c3 |

#### Card details: Contracts and fixtures

**b1. Create Postgres tables for traces and spans**

The storage schema that every other part reads or writes. It is the first contract, so the collector, the viewer API and the MCP server can be built in parallel.

- traces table: id, start time, end time, root span name, status
- spans table: id, trace id, parent span id, name, kind, start, end, status, attributes as JSON
- Indexes on trace start time and on the trace id of spans
- Ship it as a migration file under contracts/. Do not store the injected fault name on any row, so the agent cannot read the answer
- **Done when:** The migration applies to an empty Postgres database and the tables accept the fixture rows from c4.

**b2. Create the scores table linked to traces**

Stores the result of scoring, so the viewer, the API and the agent can filter failed and low-quality traces.

- scores table: trace id, label (ok, error, timeout, low_quality), numeric value, source (rule or model), created time
- One trace can have several scores
- Foreign key to traces; migration sits next to b1
- **Done when:** The migration applies cleanly and a score row cannot point at a missing trace.

**b20. Define the fixed failure taxonomy**

The fixed list of failure categories a diagnosis must choose from. The source names the six faults but does not list categories, so this card sets them.

- Proposed starting point: one category per injected fault (empty retrieval, tool schema error, truncated prompt, context overflow, weaker-model quality drop, upstream timeout) plus other
- Write a one-line definition and the span evidence that signals each category
- Store it as a JSON or enum file in contracts/ that b21, b48, b59 and b72 import
- Trade-off to record: mirroring the faults one to one makes root-cause accuracy easy to score and weaker as evidence
- **Done when:** The author has reviewed the taxonomy and every injected fault maps to exactly one category.
- **Open point:** Category list is not defined in the source document.

**b21. Pydantic model for a diagnosis: category, cause, suggested fix, spans**

The structured output of a diagnosis. The model must fill this shape, and later nodes and metrics read it.

- Pydantic model with category (from b20), cause in plain text, suggested fix, cited span ids and cluster id
- Proposed extra field: confidence
- Validation: category must be in the taxonomy and at least one span must be cited
- Used as the structured-output schema in b27
- **Done when:** Valid and invalid examples are both covered by tests.

**c7. Define span attribute names for retrieval, model-call, tool-call and error spans**

Names the attributes written on retrieval, model-call, tool-call and error spans. Medas writes them, the collector stores them and the agent reads them, so they must be fixed first.

- Retrieval: query, result count, top similarity score. Model call: model name, prompt tokens, completion tokens, context limit, finish reason. Tool call: tool name, arguments, error. Error: type, message, timeout flag
- Follow OpenTelemetry GenAI semantic conventions where a name already exists; put the rest under a project prefix such as tracescan.
- Mark which attributes can carry free text, so the outcome of d2 can be applied to them
- **Done when:** A single table in contracts/ (attribute, span kind, type, example, may hold free text) that Medas, the collector and the agent all cite.
- **Open point:** Medas writes these, the collector stores them, the agent reads them.

**c1. Write the trace API contract for list and detail (OpenAPI)**

The contract for the trace API, written before the API exists so the viewer and its mock can be built at the same time as the collector.

- GET /traces with from, to, failed_only, limit and cursor parameters, returning trace summaries with status and score
- GET /traces/{id} returning the trace and its spans with parent links
- One error shape and one pagination scheme
- Include example responses. The fixtures in c4 must validate against them
- **Done when:** An OpenAPI 3.1 file in contracts/ that passes a validator and has examples for both endpoints.

**c2. Write the MCP tool contract: tool names, inputs and outputs**

The contract for the two read-only tools the agent uses to read traces. The agent and the MCP server are built against this, not against each other.

- Tool one: list failed and low-score traces for a time window
- Tool two: get one trace with its spans
- Inputs and outputs as JSON schemas, matching the trace API shapes where possible
- State the limits: maximum traces per call and how long text fields are truncated
- **Done when:** JSON schemas in contracts/ for both tools, with example calls and results.

**c3. Define shared models: graph state, proposal, review decision and run summary**

The shared Python models that the analysis nodes, the review nodes and the metrics all pass around. Without them each feature would invent its own shapes.

- Graph state: time window, trace ids, clusters, diagnoses, proposals, decisions, run summary
- Proposal: type (create or update, proposed), title, body, regression test case, cited traces
- Review decision: proposal id, approve or reject, optional note
- Run summary: counts, token cost, wall-clock time
- **Done when:** Models import cleanly, round-trip to JSON, and are used by the fixtures in c6.

**c4. Create fixture traces: a few synthetic failed traces per fault, in the stored format**

Synthetic failed traces in the stored format. They let every other feature develop and test without the real collector or Medas.

- Three to five failed traces per injected fault, plus healthy traces and a few unrelated failures as noise
- Plain JSON, with the expected score and expected category recorded in a separate file used only by tests and metrics
- No real clinical text
- **Done when:** Fixtures validate against b1, c1 and c2, and the expected-category file covers every failed trace.
- **Open point:** Lets every other feature work without the real collector or Medas.

**c5. Seed script: load the fixture traces into Postgres**

Loads the fixture traces into a local Postgres so the MCP server can be tested against a real database.

- Applies the b1 and b2 migrations if needed, then inserts the c4 fixtures
- Idempotent: running it twice does not duplicate rows
- Takes the database URL as an argument and prints how many traces and spans were loaded
- **Done when:** After the script runs, the MCP tools b18 and b19 can be tested against that database.

**c6. Create fixture proposals and review decisions for testing review and actions**

Fixture proposals and review decisions, so the review and action nodes can be tested without the analysis nodes.

- A handful of proposals in the c3 shape, each with a regression test case
- Decision sets: all approved, all rejected, mixed, and none
- The expected dry-run output for each decision set
- **Done when:** Fixtures load through the c3 models and each decision set has an expected output.

**b22. Triage graph skeleton: shared state and a run entry point taking a time window**

The empty shell of the triage graph. It fixes the state and the entry point so the analysis and review features can each fill in their own nodes.

- LangGraph StateGraph using the c3 state, with the eight node names registered as stubs
- Entry point: run triage with a start time, an end time and a dry-run flag that defaults to on
- Returns the run summary; no node logic yet
- **Done when:** The skeleton runs end to end with stubs and returns an empty run summary.

### Trace collector and API

- **Wave:** 2 · **Tier:** MVP
- **Owns:** services/collector/
- **Goal:** Receives OpenTelemetry exports, stores and scores traces, and serves them through the trace API.
- **Builds against:** Contracts and fixtures (b1, b2, c1); Project decisions (d2)
- **Done when:** A sample OTLP export is stored; both trace API endpoints return what the contract specifies; failed traces get scores.

| Card | Area | Task | Needs |
|---|---|---|---|
| b3 | backend | Collector: accept OpenTelemetry trace exports over HTTP | b1* |
| b4 | backend | Collector: store spans linked to their trace and parent span | b3 |
| b5 | backend | Collector: redact or drop sensitive fields before storing (What to remove depends on the sensitive-data decision.) | b4, d2* |
| b11 | backend | Scoring job: mark traces that contain errors or timeouts | b4, b2* |
| b12 | backend | Scoring job: mark low-quality answers (The scoring method is not defined in the source document.) | b11 |
| b15 | backend | Trace API: list traces with time-window and failed-only filters | b4, c1* |
| b16 | backend | Trace API: get one trace with all its spans | b4, c1* |

#### Card details: Trace collector and API

**b3. Collector: accept OpenTelemetry trace exports over HTTP**

The front door of the tracing path: an HTTP endpoint that accepts OpenTelemetry exports from Medas.

- FastAPI endpoint for OTLP over HTTP (protobuf; JSON optional)
- Return success once the batch is accepted and 400 for a malformed payload
- Configuration through environment variables; no authentication in the MVP because it runs locally (proposed)
- **Done when:** A sample OTLP export posted with curl returns success.

**b4. Collector: store spans linked to their trace and parent span**

Turns accepted exports into rows in the b1 tables.

- Map OTLP resource spans to trace and span rows
- Keep trace id, span id and parent span id; attributes go in the JSON column
- Handle spans that arrive out of order or twice
- **Done when:** A multi-span sample export produces correct parent links and no duplicate rows when sent twice.

**b5. Collector: redact or drop sensitive fields before storing**

Applies the sensitive-data decision before anything is stored.

- Drop, hash or mask the attributes flagged in c7, following d2
- Keep the list of fields in configuration so it can change without code changes
- Test with a fixture that holds fake patient-like text
- **Done when:** Flagged content never reaches the database.
- **Open point:** What to remove depends on the sensitive-data decision.

**b11. Scoring job: mark traces that contain errors or timeouts**

The first part of scoring: a rule-based pass that marks traces with errors or timeouts.

- Run after spans are stored; mark a trace failed when any span has an error status or the timeout flag
- Write a row to the scores table with label error or timeout and source rule
- Safe to run again on the same trace
- **Done when:** Fixture traces with errors and timeouts are labelled, healthy ones are not, and a rerun adds no duplicate scores.

**b12. Scoring job: mark low-quality answers**

The second part of scoring: marking answers that finished without errors but are poor. The source asks for low-score traces but does not say how to score them.

- Decide the method first. Options: an LLM judge with a rubric, or a simple heuristic such as an empty or very short answer
- Record the method and its known weaknesses in the PRD metrics section
- Write a low_quality score with the numeric value
- **Done when:** The method is recorded, known-bad fixture answers are flagged and known-good ones are not.
- **Open point:** The scoring method is not defined in the source document.

**b15. Trace API: list traces with time-window and failed-only filters**

The list endpoint of the trace API, used by the viewer.

- GET /traces implementing c1
- Filters: from, to and failed_only; newest first; cursor pagination
- Response validated against the OpenAPI file in tests
- **Done when:** Responses match c1 on seeded data, and the filters return the expected traces.

**b16. Trace API: get one trace with all its spans**

The detail endpoint of the trace API, used by the viewer.

- GET /traces/{id} returning the trace header, its score and all spans with parent links
- 404 for an unknown id
- Response validated against c1
- **Done when:** A seeded trace returns every span with correct parent links.

### Medas instrumentation and fault injection

- **Wave:** 2 · **Tier:** MVP
- **Owns:** The Medas repository (location TBD, outside TraceScan)
- **Goal:** Emit the contracted spans from Medas, generate traffic, and switch on one of the six faults at a time.
- **Builds against:** Contracts and fixtures (c7); Project decisions (d2)
- **Done when:** A Medas run emits the contracted spans; each fault can be turned on alone and visibly changes the traces.

| Card | Area | Task | Needs |
|---|---|---|---|
| b13 | backend | Write a question set for Medas that exercises each injected fault | — |
| b6 | backend | Instrument Medas: one root span per request | c7*, d2* |
| b7 | backend | Instrument Medas: retrieval spans with query and result count | b6 |
| b8 | backend | Instrument Medas: model-call spans with model, prompt size and token counts | b6 |
| b9 | backend | Instrument Medas: tool-call spans with name, arguments and errors | b6 |
| b10 | backend | Record upstream timeouts and errors on spans | b8, b9 |
| b14 | backend | Traffic generator: send the question set to Medas at a set rate | b13, b6 |
| b41 | backend | Fault selector: exactly one injected fault active per run | b14 |
| b42 | backend | Fault: empty retrieval | b41, b7 |
| b43 | backend | Fault: broken tool schema | b41, b9 |
| b44 | backend | Fault: truncated system prompt | b41, b8 |
| b45 | backend | Fault: small context window | b41, b8 |
| b46 | backend | Fault: weaker model | b41, b8 |
| b47 | backend | Fault: upstream timeouts | b41, b10 |

#### Card details: Medas instrumentation and fault injection

**b13. Write a question set for Medas that exercises each injected fault**

The questions the traffic generator sends to Medas. They must exercise each injected fault, or the fault will leave no trace.

- Write 10 to 20 questions covering the topics Medas handles
- Include questions that need retrieval, questions that need a tool and questions that need long context
- Keep them in a plain file that the traffic generator reads
- Use no real patient data
- **Done when:** The set contains at least a few questions that each fault should break.

**b6. Instrument Medas: one root span per request**

Start of instrumentation: OpenTelemetry in Medas with one root span per request.

- Add the OpenTelemetry SDK and an OTLP HTTP exporter pointed at the collector
- One root span per user request, with the request id and the outcome
- Apply the d2 decision to any text put on a span
- Use the attribute names from c7
- **Done when:** A request to Medas produces one exported root span.

**b7. Instrument Medas: retrieval spans with query and result count**

Retrieval spans, so the agent can see what the search step returned.

- Child span of the root for each retrieval
- Attributes from c7: query text (subject to d2), result count, top similarity score
- **Done when:** A request that retrieves shows a retrieval span with the result count.

**b8. Instrument Medas: model-call spans with model, prompt size and token counts**

Model-call spans, so the agent can see which model ran and how much context it had.

- Child span for each model call
- Attributes from c7: model name, prompt tokens, completion tokens, context limit, finish reason
- **Done when:** Every model call shows its model name and token counts.

**b9. Instrument Medas: tool-call spans with name, arguments and errors**

Tool-call spans, so the agent can see which tool was called and whether it failed.

- Child span for each tool call
- Attributes from c7: tool name, arguments, result size, error
- **Done when:** A tool call shows its name and arguments, and a failing call shows its error.

**b10. Record upstream timeouts and errors on spans**

Makes sure failures and timeouts are recorded on the spans, since the agent can only diagnose what it can see.

- Set the span status to error and attach the exception type and message
- Mark timeouts with the timeout flag from c7
- Cover failures from the model provider, the tools and retrieval
- **Done when:** A forced timeout and a forced exception each show up on the right span.

**b14. Traffic generator: send the question set to Medas at a set rate**

Sends the question set to Medas at a set rate, so each fault run produces enough traffic to cluster.

- Script that reads the b13 questions and sends them at a configurable rate and duration
- Give each run an opaque run id. Write the run id and active fault to a separate ground-truth file, never onto spans
- Report how many requests succeeded and how many failed
- **Done when:** A run produces traces in the collector and the ground-truth file lists the run id.

**b41. Fault selector: exactly one injected fault active per run**

The switch that turns exactly one fault on, so each eval run has a known cause.

- One setting (an environment variable, proposed) names the active fault; unset means healthy
- Refuse to start when more than one fault is selected
- Write the active fault to the run log, not to span attributes
- **Done when:** Each of the six values selects its fault and a healthy run is possible.

**b42. Fault: empty retrieval**

Injected fault 1 of 6: the retrieval step returns nothing.

- When on, the retrieval step returns no results
- Expected signal: retrieval spans with result count 0, and answers that have no support
- **Done when:** With the fault on, retrieval spans show zero results and answers are unsupported.

**b43. Fault: broken tool schema**

Injected fault 2 of 6: a tool schema that no longer matches what the tool accepts.

- When on, a tool is declared with a schema that does not match its real inputs
- Expected signal: tool-call spans with validation errors
- **Done when:** With the fault on, calls to that tool fail with a schema error.

**b44. Fault: truncated system prompt**

Injected fault 3 of 6: the system prompt is cut short.

- When on, truncate the system prompt, for example to half its length
- Expected signal: a smaller prompt token count and answers that ignore the cut rules
- **Done when:** With the fault on, model-call spans show a smaller prompt than in a healthy run.

**b45. Fault: small context window**

Injected fault 4 of 6: a context window too small for the input.

- When on, limit the context so retrieved passages or history are dropped
- Expected signal: context limit reached, a finish reason of length, or missing passages
- **Done when:** With the fault on, model-call spans show the reduced limit.

**b46. Fault: weaker model**

Injected fault 5 of 6: a weaker model replaces the normal one.

- When on, switch model calls to a smaller model
- Expected signal: a different model name and lower answer quality with no errors. This is the hardest fault for rule-based scoring and depends on b12
- **Done when:** With the fault on, model-call spans show the weaker model.

**b47. Fault: upstream timeouts**

Injected fault 6 of 6: upstream timeouts.

- When on, make a dependency (the model provider or a tool) slow or time out for a share of requests
- Expected signal: timeout-flagged spans on part of the traffic
- **Done when:** With the fault on, a share of requests ends in recorded timeouts.

### Read-only MCP server

- **Wave:** 2 · **Tier:** MVP
- **Owns:** services/mcp_server/
- **Goal:** The only way the agent reads traces. Read-only by database role, not by convention.
- **Builds against:** Contracts and fixtures (b1, c2, c5)
- **Done when:** Both tools return contracted output against seeded fixtures, and a write attempt fails.

| Card | Area | Task | Needs |
|---|---|---|---|
| b17 | backend | MCP server: skeleton using a read-only database role | b1*, c2* |
| b18 | backend | MCP tool: list failed and low-score traces for a time window | b17, c5* |
| b19 | backend | MCP tool: get one trace with its spans | b17, c5* |

#### Card details: Read-only MCP server

**b17. MCP server: skeleton using a read-only database role**

The MCP server shell. The agent can only read traces through it, and the database itself enforces that it cannot write.

- FastMCP server using the c2 contract
- Connects to Postgres with a role granted SELECT only on the trace tables
- A test shows that an insert through this connection is rejected by the database
- **Done when:** The server starts, lists its two tools and cannot write.

**b18. MCP tool: list failed and low-score traces for a time window**

The tool that lists failed and low-score traces for a time window. It is the agent's way in.

- Inputs: window start, window end and an optional limit
- Returns traces that are failed or have a low_quality score, with summary fields only
- Tested against a database seeded by c5
- **Done when:** Returns exactly the failed and low-score fixture traces inside the window.

**b19. MCP tool: get one trace with its spans**

The tool that returns one trace with all its spans, for diagnosis.

- Input: trace id; output: the trace with every span
- Truncate very long text fields and say so in the output, as defined in c2
- Return a clear error for an unknown id
- **Done when:** Returns a full fixture trace and an error for a missing one.

### Trace viewer UI

- **Wave:** 2 · **Tier:** MVP
- **Owns:** ui/ (trace viewer routes and components)
- **Goal:** Next.js pages to browse runs and inspect a trace, built against a mock of the trace API.
- **Builds against:** Contracts and fixtures (c1, c4)
- **Done when:** List, filters, detail, span tree, span panel and badges work against the mock API.

| Card | Area | Task | Needs |
|---|---|---|---|
| f1 | frontend | Create the Next.js app with page layout and navigation | — |
| m1 | frontend | Mock trace API server that serves the fixtures, from the contract | c1*, c4* |
| f2 | frontend | Runs list page: table of traces with time, status and score | f1, m1 |
| f3 | frontend | Runs list: time-window and failed-only filters | f2 |
| f4 | frontend | Trace detail page: header with timing, status and score | f1, m1 |
| f5 | frontend | Trace detail: span tree with nesting and durations | f4 |
| f6 | frontend | Trace detail: span panel showing inputs, outputs and errors | f5 |
| f7 | frontend | Failure and low-score badges on the list and the detail page | f2, f4 |

#### Card details: Trace viewer UI

**f1. Create the Next.js app with page layout and navigation**

The empty app: page layout and navigation, so every other UI card has somewhere to live.

- Next.js app with TypeScript and a runs page route
- Layout with header and navigation
- API base URL read from an environment variable, so the mock and the real API can be swapped
- **Done when:** The app starts and shows the layout with a placeholder runs page.

**m1. Mock trace API server that serves the fixtures, from the contract**

A small server that behaves like the trace API, so the UI can be built before the collector exists.

- Implements the c1 contract and serves the c4 fixtures
- Supports the same filters as the real API
- Used for development only
- **Done when:** The UI can list and open fixture traces with no other service running.

**f2. Runs list page: table of traces with time, status and score**

The first page a user sees: all runs in a table.

- Columns: time, root span name, duration, status and score
- Loading, empty and error states
- Each row links to the trace detail page
- **Done when:** The table shows every fixture trace and each row opens the detail page.

**f3. Runs list: time-window and failed-only filters**

Lets the user narrow the list to the window and the failures they care about.

- Time window picker with presets (last hour, last 24 hours) and a custom range
- Failed-only toggle
- Keep the filters in the URL so a view can be shared
- **Done when:** Changing a filter changes the list and survives a page reload.

**f4. Trace detail page: header with timing, status and score**

The top of a trace's page: the facts about the whole run.

- Show trace id, start time, total duration, status and score
- A not-found state for an unknown id
- **Done when:** A fixture trace shows the right header and an unknown id shows not found.

**f5. Trace detail: span tree with nesting and durations**

Shows how a request unfolded, step by step.

- Spans nested by parent
- Each row shows span name, kind and duration, with a bar sized against the trace duration
- Expand and collapse
- **Done when:** The tree for a fixture trace matches its parent links.

**f6. Trace detail: span panel showing inputs, outputs and errors**

The panel where a person reads the evidence in one span.

- Click a span to open its attributes, inputs, outputs and error message
- Long text collapses
- Content may be sensitive, so follow d2
- **Done when:** Selecting a span shows all its stored fields, including an error when there is one.

**f7. Failure and low-score badges on the list and the detail page**

Makes failed and low-score runs easy to spot.

- Badges for Failed, Timeout and Low score
- Shown on list rows, in the detail header and on spans with errors
- Use text as well as colour
- **Done when:** A failed fixture shows its badge on the list and the detail page.

### Triage analysis nodes

- **Wave:** 2 · **Tier:** MVP
- **Owns:** agent/analysis/
- **Goal:** Collect, cluster, diagnose and draft nodes, developed against a stub MCP client that serves fixtures.
- **Builds against:** Contracts and fixtures (c2, c4, b22, b21)
- **Done when:** Given fixture traces the nodes produce validated diagnoses and issue proposals with regression tests.

| Card | Area | Task | Needs |
|---|---|---|---|
| a1 | backend | Stub MCP client that serves the fixture traces | c2*, c4* |
| b23 | backend | collect_traces node: fetch failed traces through the MCP client interface | b22*, a1 |
| b24 | backend | Turn each failed trace into text and an embedding | b23 |
| b25 | backend | cluster_failures: HDBSCAN grouping, with noise kept apart | b24 |
| b26 | backend | End the run cleanly when no clusters are found | b25 |
| b27 | backend | diagnose_cluster: prompt and structured output for one cluster | b21*, b25 |
| b28 | backend | Run diagnose_cluster in parallel, one branch per cluster | b27 |
| b29 | backend | Check that every span a diagnosis cites exists in its cluster | b28 |
| b30 | backend | draft_proposals: issue title and body from a diagnosis | b29 |
| b31 | backend | draft_proposals: regression test case from the failing input | b30 |
| b32 | backend | Track token cost and wall-clock time for each run | b22* |

#### Card details: Triage analysis nodes

**a1. Stub MCP client that serves the fixture traces**

A stand-in for the real MCP client. It lets the analysis nodes run with no database and no server.

- Same interface the real client will have: list failed traces for a window, get one trace
- Reads the c4 fixtures and returns the c2 shapes
- Switched to the real client by configuration in i3
- **Done when:** The nodes can be tested end to end with this client alone.

**b23. collect_traces node: fetch failed traces through the MCP client interface**

First node of the graph: gathers the failed traces for the run's window.

- Call the list tool for the window, then the get tool for each trace
- Cap the number of traces per run (proposed) and note when the cap is hit
- Put the full traces into graph state
- **Done when:** With the stub client, state holds every failed fixture trace.

**b24. Turn each failed trace into text and an embedding**

Prepares traces for clustering by turning each into a short text and a vector.

- Build a short text per trace: failing span name, error message and key attributes, trimmed to a size limit
- Embed with an embedding model (the choice is TBD; record its cost)
- Cache embeddings by trace id
- **Done when:** Each failed trace has a text and a vector of the same size.

**b25. cluster_failures: HDBSCAN grouping, with noise kept apart**

Groups similar failures so one issue can be drafted per cause rather than per trace.

- Run HDBSCAN on the vectors; label -1 is noise and is kept apart, not forced into a cluster
- min_cluster_size is a parameter. With 3 to 5 traces per fault in the fixtures, expect a small value (starting value TBD; tune on the fixtures)
- Output clusters with their trace ids
- **Done when:** On the fixtures, traces for the same fault land in the same cluster.

**b26. End the run cleanly when no clusters are found**

Handles the case where there is nothing to diagnose.

- Conditional edge: zero clusters goes to the end of the graph
- The run summary states that no clusters were found and how many traces were noise
- No review step starts
- **Done when:** A run over healthy fixtures ends cleanly with that message.

**b27. diagnose_cluster: prompt and structured output for one cluster**

The diagnosing step: one model call that explains a cluster.

- Give the model a sample of traces from the cluster, with spans trimmed
- Ask for the b21 model as structured output
- The prompt lists the b20 categories with their definitions
- Record the tokens used, for b32
- **Done when:** Each fixture cluster returns a valid diagnosis; invalid output is retried once (proposed).

**b28. Run diagnose_cluster in parallel, one branch per cluster**

Diagnoses all clusters at the same time.

- Use LangGraph Send to start one diagnose branch per cluster
- Collect the results back into state in a stable order
- A failing branch is recorded and does not stop the others
- **Done when:** Three clusters produce three diagnoses and one forced failure leaves the other two intact.

**b29. Check that every span a diagnosis cites exists in its cluster**

A guard against made-up evidence: every span a diagnosis cites must really be in its cluster.

- Deterministic check, no model call
- On failure, retry the diagnosis once, then drop it and note this in the run summary (proposed)
- **Done when:** A diagnosis that cites an unknown span is rejected.

**b30. draft_proposals: issue title and body from a diagnosis**

Turns a checked diagnosis into the issue a person will review.

- Short, specific title
- Body: summary, cause, evidence (trace and span ids), suggested fix and the number of affected traces
- Follow d2 on what content may be quoted
- **Done when:** Each fixture diagnosis gives a proposal that a reviewer can understand without opening the code.

**b31. draft_proposals: regression test case from the failing input**

Adds the regression test that makes the fix checkable.

- Take the failing input and the expected correct behaviour from the diagnosis
- Output a case record that can be appended to an eval dataset (format defined in c3)
- Readable without opening the trace
- **Done when:** Each proposal carries a regression case that matches its diagnosis.

**b32. Track token cost and wall-clock time for each run**

Measures what a run costs, since cost and time per run are two of the success metrics.

- Sum token usage over every model and embedding call in the run
- Convert to cost with a price table in configuration
- Record wall-clock time per node and in total, and write both to the run summary
- **Done when:** The run summary shows cost and time for a fixture run.

### Human review and dry-run actions

- **Wave:** 2 · **Tier:** MVP
- **Owns:** agent/review/, agent/actions/
- **Goal:** Pause for approval, resume with decisions, and write approved items as local files.
- **Builds against:** Contracts and fixtures (b22, c6)
- **Done when:** Given fixture proposals, nothing is written without approval and approved items appear as local files.

| Card | Area | Task | Needs |
|---|---|---|---|
| b33 | backend | Set up the Postgres checkpointer so a run can wait | b22* |
| b34 | backend | human_review: pause the run with its proposals | b33, c6* |
| b35 | backend | Terminal review: show proposals and collect approve or reject for each (The review UI is stretch in the source, so the MVP reviews in the terminal.) | b34 |
| b36 | backend | Resume the run with decisions; end it if nothing is approved | b35 |
| b37 | backend | apply_actions: process approved proposals only | b36 |
| b38 | backend | Add the dry-run flag, on by default | b37 |
| b39 | backend | Dry run: write each approved issue to a local file | b38 |
| b40 | backend | Dry run: write each approved regression case to a local eval dataset file | b38 |

#### Card details: Human review and dry-run actions

**b33. Set up the Postgres checkpointer so a run can wait**

Lets a run stop and be resumed later, which human review needs.

- Postgres checkpointer for the graph
- One thread id per run
- State is saved after each step
- **Done when:** Stop the process mid-run, restart it and resume from the saved state.

**b34. human_review: pause the run with its proposals**

The pause point where the agent hands its proposals to a person.

- The human_review node calls interrupt() with the proposals
- Nothing after this node runs until a decision arrives
- **Done when:** A run over the c6 fixture proposals stops here and reports that it is waiting.

**b35. Terminal review: show proposals and collect approve or reject for each**

A terminal review, since the review dashboard is stretch.

- A command that lists runs waiting for review
- Shows each proposal with its title, body and regression test
- Collects approve or reject for each proposal, with an optional note
- Shows a summary before submitting
- **Done when:** A person can review a fixture run in the terminal and get a decision list.
- **Open point:** The review UI is stretch in the source, so the MVP reviews in the terminal.

**b36. Resume the run with decisions; end it if nothing is approved**

Resumes the paused run with the person's decisions.

- Resume the graph with the decision list
- If every proposal is rejected, end the run without calling apply_actions
- Reject an incomplete list: every proposal needs a decision
- **Done when:** Approved decisions continue to apply_actions and all-rejected ends the run.

**b37. apply_actions: process approved proposals only**

The action step. It is where the human gate becomes real: only approved proposals pass.

- Loop over approved proposals only
- Send each to the writer chosen by the dry-run flag
- Test with a fake writer
- **Done when:** Rejected proposals produce no output in any mode.

**b38. Add the dry-run flag, on by default**

The safety switch: nothing is sent to the outside world unless this is turned off.

- Flag in configuration and on the command line, default on
- Every real-write path must check it
- The run summary states whether the run was a dry run
- **Done when:** A run with no flag set behaves as a dry run.

**b39. Dry run: write each approved issue to a local file**

What dry run does for an issue: write it to a local file instead of GitHub.

- One markdown file per approved issue, in an output folder
- File name from the proposal id; the content is the issue title and body
- Do not overwrite existing files by accident (proposed)
- **Done when:** Approving a fixture proposal creates a readable issue file.

**b40. Dry run: write each approved regression case to a local eval dataset file**

What dry run does for a regression test: write it to a local eval dataset.

- Append one JSON line per approved regression case to a dataset file
- Skip a case already present, keyed by proposal id
- **Done when:** Approving a fixture proposal adds exactly one line to the dataset, and approving it again adds none.

### Eval ground truth and metrics

- **Wave:** 2 · **Tier:** MVP
- **Owns:** eval/metrics/
- **Goal:** Fault-to-category ground truth and the metric calculators, tested on fixture results.
- **Builds against:** Contracts and fixtures (b20, c3, c4)
- **Done when:** Each metric returns the expected value on fixture results and the results table is written.

| Card | Area | Task | Needs |
|---|---|---|---|
| b48 | backend | Ground-truth file: each fault with its expected category | b20* |
| b50 | backend | Metric: detection rate | b48, c3*, c4* |
| b51 | backend | Metric: root-cause accuracy | b50 |
| b52 | backend | Metric: false positives | b50 |
| b53 | backend | Metric: duplicate issues on a second run | c3*, c4* |
| b54 | backend | Metric: cost and time per run | c3*, c4* |
| b55 | backend | Write the eval results table to a file | b51, b52, b53, b54 |

#### Card details: Eval ground truth and metrics

**b48. Ground-truth file: each fault with its expected category**

The answer key for the evaluation: what each injected fault should be diagnosed as.

- Six rows: fault name, expected category (from b20) and the span signal that should appear
- Stored in eval/ and kept where the agent cannot read it
- **Done when:** Every fault has one expected category.

**b50. Metric: detection rate**

Metric 1: how many of the injected faults TraceScan found.

- Proposed definition: a fault is detected when at least one proposal matches its expected category. Rate = detected faults divided by 6
- Test on fixture results with known outcomes
- **Done when:** Returns the expected value on a hand-made result set.

**b51. Metric: root-cause accuracy**

Metric 2: of the faults found, how often the diagnosis names the right cause.

- Proposed definition: among detected faults, the share whose diagnosed category equals the ground-truth category
- Test with a result set that has one wrong category
- **Done when:** Returns the expected value on a hand-made result set.

**b52. Metric: false positives**

Metric 3: reported issues that match no injected fault.

- Proposed definition: proposals whose category and traces match no fault, as a count and as a share of all proposals
- Includes proposals from a healthy run
- **Done when:** Returns the expected value on a hand-made result set.

**b53. Metric: duplicate issues on a second run**

Metric 4: repeat issues when the same traffic is triaged twice.

- Run the same window twice; count proposals in the second run that repeat one from the first
- In the MVP this is the baseline. It should fall to 0 once known-issues memory exists
- **Done when:** Returns the expected value on a hand-made pair of runs.

**b54. Metric: cost and time per run**

Metrics 5 and 6: spend and wall-clock time per run.

- Read cost and time from each run summary (b32)
- Report per fault, mean and total
- **Done when:** Returns the expected values on fixture run summaries.

**b55. Write the eval results table to a file**

The evaluation output: one table with all metrics.

- One row per fault; columns for each metric
- Written as markdown and CSV in eval/results/
- Includes the run date and the configuration used
- **Done when:** A table is produced from fixture results with every metric filled in.

### MVP integration and eval run

- **Wave:** 3 · **Tier:** MVP
- **Owns:** Lead agent; wiring and run scripts only
- **Goal:** Joins the parts and runs the full fault-injection eval. Done by the lead after the parallel features land.
- **Builds against:** Medas instrumentation and fault injection (b10, b14, b42, b43, b44, b45, b46, b47); Trace collector and API (b4, b15, b16); Trace viewer UI (f7); Triage analysis nodes (b31, b32); Human review and dry-run actions (b40); Read-only MCP server (b18, b19); Eval ground truth and metrics (b55)
- **Done when:** Medas traces reach the viewer and the agent, and the eval has run on all six faults.

| Card | Area | Task | Needs |
|---|---|---|---|
| i1 | backend | Send Medas spans to the real collector and confirm they are stored | b10*, b4* |
| i2 | frontend | Point the trace viewer at the real trace API | f7*, b15*, b16*, i1 |
| i4 | backend | Wire the analysis and review nodes into one graph and run it on fixtures | b31*, b40* |
| i3 | backend | Run the full graph against the real MCP server and real Medas traces | i4, b18*, b19*, i1 |
| b49 | backend | Eval runner: for each fault, generate traffic and run TraceScan | b14*, b42*, b43*, b44*, b45*, b46*, b47*, b32*, i3 |
| e1 | backend | Run the full eval and save the results table | b49, b55* |

#### Card details: MVP integration and eval run

**i1. Send Medas spans to the real collector and confirm they are stored**

First real join: Medas spans reach the real collector.

- Run Medas with the exporter pointed at the collector and send a short batch with b14
- Check traces and spans exist with correct parent links
- Report any mismatch with c7 to the lead; contracts change only through the lead
- **Done when:** A Medas request is stored and its span tree is complete.

**i2. Point the trace viewer at the real trace API**

Second real join: the viewer reads real data.

- Point the API base URL at the real trace API instead of the mock
- Click through list, filters, detail, span tree and span panel on real traces
- List any field the mock had that the API lacks
- **Done when:** The viewer works on traces that Medas produced.

**i4. Wire the analysis and review nodes into one graph and run it on fixtures**

Joins the analysis and review parts and checks them together on fixtures.

- Connect the nodes in order: collect, cluster, diagnose in parallel, draft, human review, apply. The replay and match nodes stay as pass-through for the MVP
- Run with the stub client and fixture decisions
- Check the run summary and the output files
- **Done when:** A fixture run goes from window to dry-run files through the one graph.

**i3. Run the full graph against the real MCP server and real Medas traces**

Third real join: the graph runs on real Medas traces.

- Switch the MCP client from the stub to the real server
- Run on traces from a faulty Medas run
- Check that clusters, diagnoses and proposals look sensible, review in the terminal and check the dry-run files
- **Done when:** One full run on real traces ends in dry-run output.

**b49. Eval runner: for each fault, generate traffic and run TraceScan**

Automates the evaluation, so every fault is tested the same way.

- For each of the six faults: turn the fault on, generate traffic with b14, wait for collection and scoring, run TraceScan on that window, and save the run summary and proposals
- Add a healthy run to count false positives (proposed)
- Triage the last window a second time to measure duplicates
- Eval runs approve proposals automatically, with dry run on, so no person is needed (proposed)
- **Done when:** One command runs all faults and leaves the raw results on disk.

**e1. Run the full eval and save the results table**

The evaluation itself: the numbers the MVP gate is judged on.

- Run b49 over all faults, compute b50 to b54 and write the b55 table
- Keep the raw run summaries next to the table
- Note any run that failed and why
- **Done when:** A results table exists for all six faults.

### Baseline, thresholds and MVP gate

- **Wave:** 4 · **Tier:** MVP
- **Owns:** The author, not an agent
- **Goal:** Time a manual triage, set metric thresholds from the results, and decide what stretch work to cut.
- **Builds against:** Medas instrumentation and fault injection (b41, b14); MVP integration and eval run (e1)
- **Done when:** Thresholds are recorded in the PRD and a go or cut decision is made for stretch work.

| Card | Area | Task | Needs |
|---|---|---|---|
| s1 | shared | Time one manual triage of a faulty run as the baseline (Gives the PRD its missing evidence that the problem is real.) | b41*, b14* |
| s2 | shared | Set success thresholds for each metric from the results | e1*, s1 |
| g1 | shared | MVP gate, day 10: review results and cut stretch work if behind | s2 |

#### Card details: Baseline, thresholds and MVP gate

**s1. Time one manual triage of a faulty run as the baseline**

Gives the PRD its missing evidence: how long finding the cause by hand takes today.

- Pick one faulty run
- Open the traces in the viewer and find the pattern by hand
- Time it from start to written diagnosis, and write the time and the diagnosis in the PRD Evidence section
- **Done when:** The PRD holds a measured manual time.
- **Open point:** Gives the PRD its missing evidence that the problem is real.

**s2. Set success thresholds for each metric from the results**

Replaces the TBD targets in the PRD with numbers.

- Read the e1 results and the s1 baseline
- Set a target for each metric in the Success Metrics table
- State what counts as failing
- **Done when:** No metric in the PRD is left as TBD for the MVP.

**g1. MVP gate, day 10: review results and cut stretch work if behind**

The day 10 checkpoint. It decides whether stretch work goes ahead.

- Compare milestones 1 to 4 with their outcomes in the PRD
- If behind, name the stretch milestones that are cut
- Update milestone status in the PRD
- **Done when:** A go or cut decision is written down for each stretch feature.

### Replay reproduction

- **Wave:** 5 · **Tier:** Stretch
- **Owns:** agent/reproduce/ and a sandbox endpoint in Medas
- **Goal:** Replay a diagnosed failure against Medas and drop clusters that do not reproduce.
- **Builds against:** Baseline, thresholds and MVP gate (g1); Contracts and fixtures (c4, b20); Triage analysis nodes (b28, b30)
- **Done when:** Reproduced and unreproduced fixtures are told apart, and unreproduced ones never reach review.

| Card | Area | Task | Needs |
|---|---|---|---|
| b56 | backend | Sandbox endpoint in Medas: run it on given inputs | g1* |
| b57 | backend | Extract the replay inputs from a cluster's traces | g1*, c4* |
| b58 | backend | reproduce_failure node: replay each diagnosis in parallel | b57, b56, b28* |
| b59 | backend | Rule for what counts as reproduced, per failure category (Not defined in the source document.) | b58, b20* |
| b60 | backend | draft_proposals: drop clusters that did not reproduce | b59, b30* |

#### Card details: Replay reproduction

**b56. Sandbox endpoint in Medas: run it on given inputs**

A way to run Medas again on a given input, so a diagnosis can be tested.

- Endpoint in Medas that takes a question and the fault settings and returns the answer and a trace id
- Local only, and it must not touch production data (proposed)
- **Done when:** A call returns an answer and the trace of that call.

**b57. Extract the replay inputs from a cluster's traces**

Picks what to replay for each cluster.

- From a cluster's traces take the original user input and any parameters needed
- Choose a few representative inputs and remove duplicates
- **Done when:** Each fixture cluster yields its replay inputs.

**b58. reproduce_failure node: replay each diagnosis in parallel**

Tries the failure again for each diagnosis, at the same time.

- Use LangGraph Send: one replay per cluster
- Call the b56 endpoint and collect the output and the new trace
- **Done when:** Each cluster comes back with its replay results.

**b59. Rule for what counts as reproduced, per failure category**

Decides what counts as reproduced. The source does not define this.

- Write one rule per taxonomy category using span evidence, for example: empty retrieval is reproduced when the replay again returns zero results
- Model output varies, so decide whether to replay each input several times (TBD)
- Keep the rules as code with tests on fixture replays
- **Done when:** Reproduced and unreproduced fixtures are told apart.
- **Open point:** Not defined in the source document.

**b60. draft_proposals: drop clusters that did not reproduce**

Stops unconfirmed causes from reaching a reviewer.

- Remove clusters marked not reproduced before proposals are drafted
- List the dropped clusters and the reason in the run summary
- **Done when:** An unreproduced fixture cluster produces no proposal.

### Known-issues memory

- **Wave:** 5 · **Tier:** Stretch
- **Owns:** agent/memory/
- **Goal:** Remember issues from earlier runs so a repeat failure updates an issue instead of duplicating it.
- **Builds against:** Baseline, thresholds and MVP gate (g1); Contracts and fixtures (b1); Human review and dry-run actions (b39); Triage analysis nodes (b25, b30)
- **Done when:** A second run over the same traffic produces updates, not new issues.

| Card | Area | Task | Needs |
|---|---|---|---|
| b61 | backend | Create the known-issues table | g1*, b1* |
| b62 | backend | Save each applied proposal to the known-issues table | b61, b39* |
| b63 | backend | match_known_issues: compare a cluster with stored issues | b61, b25* |
| b64 | backend | draft_proposals: update-existing-issue proposal type | b63, b30* |
| b65 | backend | apply_actions: update an existing issue instead of creating one | b64, b62 |

#### Card details: Known-issues memory

**b61. Create the known-issues table**

The long-term store of issues from earlier runs.

- Fields: id, category, summary, embedding or cluster signature, first seen, last seen, occurrence count, link (file path or issue URL), status
- Migration
- **Done when:** The migration applies and rows can be stored and read.

**b62. Save each applied proposal to the known-issues table**

Remembers what was filed.

- After a proposal is applied, insert a row
- Do this in dry run too, so the duplicate metric can be measured (proposed)
- **Done when:** Applying a fixture proposal adds one known-issue row.

**b63. match_known_issues: compare a cluster with stored issues**

Recognises a failure seen before.

- Compare the cluster with stored issues by embedding similarity
- Return the closest match above a threshold, or none (threshold TBD; tune on fixtures)
- **Done when:** A repeat fixture cluster matches its stored issue and a new one does not.

**b64. draft_proposals: update-existing-issue proposal type**

Adds a second kind of proposal: update an existing issue instead of opening a new one.

- When a match exists, draft an update that adds the new occurrences and evidence
- Reviewer sees which issue it would update
- **Done when:** A matched cluster produces an update proposal.

**b65. apply_actions: update an existing issue instead of creating one**

Carries out an update in dry run.

- For an update proposal, append to the existing issue file and raise the occurrence count
- Do not create a new file
- **Done when:** A second run over the same traffic produces updates and no new issues.

### GitHub issues

- **Wave:** 6 · **Tier:** Stretch
- **Owns:** agent/github/
- **Goal:** Create and update real GitHub issues, only when dry run is off.
- **Builds against:** Baseline, thresholds and MVP gate (g1); Human review and dry-run actions (b37, b38); Project decisions (d2); Known-issues memory (b64)
- **Done when:** With dry run off an approved proposal becomes an issue; with it on nothing is sent.

| Card | Area | Task | Needs |
|---|---|---|---|
| b66 | backend | GitHub client: create an issue | g1*, b37*, d2* |
| b67 | backend | GitHub client: update an existing issue | b66, b64* |
| b68 | backend | Send GitHub writes only when dry run is off | b66, b38* |

#### Card details: GitHub issues

**b66. GitHub client: create an issue**

First real write: create an issue on GitHub.

- Use the GitHub REST API with a token from the environment; repository from configuration
- Create the issue with title, body and a tracescan label
- Return the issue URL and store it with the known issue
- Never log the token
- **Done when:** An approved proposal becomes an issue in a test repository.

**b67. GitHub client: update an existing issue**

Update an issue that already exists.

- Add a comment or edit the body of the stored issue
- Find the issue through the URL stored in the known-issues table
- **Done when:** An update proposal changes the right issue.

**b68. Send GitHub writes only when dry run is off**

The guard that keeps GitHub writes behind dry run.

- Route every write through one function that checks the dry-run flag
- Test that with dry run on no network call is made
- **Done when:** With dry run on nothing is sent, and with it off a write is made.

### Review dashboard

- **Wave:** 5 · **Tier:** Stretch
- **Owns:** ui/review/, services/review_api/
- **Goal:** Replace the terminal review with a web dashboard, built against a review API contract.
- **Builds against:** Human review and dry-run actions (b34, b36); Baseline, thresholds and MVP gate (g1); Trace viewer UI (f1, f5)
- **Done when:** A person can approve or reject each proposal in the browser and the run resumes.

| Card | Area | Task | Needs |
|---|---|---|---|
| c8 | backend | Write the review API contract | b34*, g1* |
| b75 | backend | Review API: list runs waiting for review with their proposals | c8 |
| b76 | backend | Review API: submit decisions and resume the run | c8, b75, b36* |
| f8 | frontend | Review page: runs waiting for review, built against a mock of the review API | f1*, c8 |
| f9 | frontend | Proposal card: issue title, body and regression test | f8 |
| f10 | frontend | Evidence panel: cluster traces linking to the trace viewer | f9, f5* |
| f11 | frontend | Show whether the failure reproduced, when that data is present | f9 |
| f12 | frontend | Approve and reject controls on each proposal | f9 |
| f13 | frontend | Submit decisions and resume the run | f12 |
| f14 | frontend | Show the result after apply: dry-run file or GitHub issue link | f13 |
| i5 | frontend | Connect the review dashboard to the real review API | f14, b76 |

#### Card details: Review dashboard

**c8. Write the review API contract**

The contract between the dashboard and its API, so both can be built at once.

- List runs waiting for review, with proposals and evidence trace ids
- Submit decisions
- Return the apply result (file path or issue URL)
- OpenAPI, as in c1
- **Done when:** An OpenAPI file with examples.

**b75. Review API: list runs waiting for review with their proposals**

The read side of review.

- Endpoint listing runs waiting for review
- Each run includes its proposals and cited traces
- **Done when:** Returns the runs that are paused in a seeded test.

**b76. Review API: submit decisions and resume the run**

The write side of review: decisions come in and the run resumes.

- Endpoint that takes a decision list and resumes the run using the b36 logic
- Return the apply result
- Reject a run that has already been decided
- **Done when:** A submitted decision list resumes the run and returns its outcome.

**f8. Review page: runs waiting for review, built against a mock of the review API**

The first dashboard page: runs that need a decision.

- List of runs waiting for review
- Built against a mock of the c8 API
- Empty, loading and error states
- **Done when:** The page lists the mocked runs.

**f9. Proposal card: issue title, body and regression test**

How one proposal reads.

- Title, body rendered as markdown and the regression test in a code block
- Shows which traces it is based on
- **Done when:** A mocked proposal shows all three parts.

**f10. Evidence panel: cluster traces linking to the trace viewer**

Lets the reviewer check the evidence before deciding.

- List the cluster's traces
- Each links to the trace viewer, and to the cited span when there is one
- **Done when:** Each evidence link opens the right trace.

**f11. Show whether the failure reproduced, when that data is present**

Shows whether a failure was reproduced, once replay exists.

- Show a reproduced or not reproduced badge only when the data is present
- Hidden otherwise
- **Done when:** A proposal with replay data shows the badge and one without shows none.

**f12. Approve and reject controls on each proposal**

The decision controls.

- Approve and reject buttons on each proposal, with an optional note
- State is kept per proposal and can be changed before submitting
- **Done when:** Each proposal can be approved, rejected or changed back.

**f13. Submit decisions and resume the run**

Sends the decisions and resumes the run.

- Submit is disabled until every proposal has a decision
- Confirm step, loading and error states
- Calls the review API and shows that the run resumed
- **Done when:** A complete set of decisions can be submitted to the mock.

**f14. Show the result after apply: dry-run file or GitHub issue link**

Shows what happened after approval.

- For each approved proposal show the dry-run file path or the GitHub issue link
- Rejected proposals show as rejected
- **Done when:** The result view matches the submitted decisions.

**i5. Connect the review dashboard to the real review API**

Last dashboard join: the real review API.

- Switch from the mock to the real API
- Approve one proposal end to end and check the dry-run output
- **Done when:** A person can review and resume a real paused run in the browser.

### MAST-Data benchmark

- **Wave:** 3 · **Tier:** Stretch
- **Owns:** eval/mast/
- **Goal:** Compare the diagnoser with human labels on the published MAST-Data benchmark.
- **Builds against:** Project decisions (d4); Contracts and fixtures (b20); Triage analysis nodes (b28)
- **Done when:** An agreement figure between the diagnoser and the human labels is reported.

| Card | Area | Task | Needs |
|---|---|---|---|
| b71 | backend | Load the MAST-Data benchmark traces | d4* |
| b72 | backend | Map MAST-Data failure labels onto the taxonomy | b71, b20* |
| b73 | backend | Run the diagnoser over the MAST-Data traces | b72, b28* |
| b74 | backend | Report agreement between the diagnoser and human labels | b73 |

#### Card details: MAST-Data benchmark

**b71. Load the MAST-Data benchmark traces**

Brings in the outside benchmark traces.

- Check the dataset format and licence first
- Convert each trajectory to the stored trace format, or to text the diagnoser accepts
- Use a sample size you can afford (cost TBD)
- **Done when:** The chosen sample loads and each item has its human label.

**b72. Map MAST-Data failure labels onto the taxonomy**

Makes the benchmark's labels comparable with the failure taxonomy.

- Write a mapping table from each benchmark label to a taxonomy category, or to unmapped
- Taxonomy changes go through the lead
- Report how many labels could not be mapped
- **Done when:** Every benchmark label has a mapping or is marked unmapped.

**b73. Run the diagnoser over the MAST-Data traces**

Runs the agent's diagnosis on the benchmark.

- Reuse the diagnose step on each benchmark item
- Record the predicted category and the tokens used
- **Done when:** Each sampled item has a predicted category.

**b74. Report agreement between the diagnoser and human labels**

The result: how well the agent agrees with human labels.

- Report the agreement rate, with a breakdown by label
- Compare with a simple baseline such as always guessing the most common label (proposed)
- **Done when:** An agreement figure is written next to the baseline.

### Stretch evaluation rerun

- **Wave:** 6 · **Tier:** Stretch
- **Owns:** eval/ (run scripts and results only)
- **Goal:** Re-run the eval with replay and memory switched on and compare with the MVP run.
- **Builds against:** Replay reproduction (b60); Known-issues memory (b65); MVP integration and eval run (e1)
- **Done when:** A before and after comparison of duplicates and false positives is recorded.

| Card | Area | Task | Needs |
|---|---|---|---|
| b69 | backend | Re-run the eval with replay and memory switched on | b60*, b65*, e1* |
| b70 | backend | Compare duplicate and false-positive rates with the MVP run | b69 |

#### Card details: Stretch evaluation rerun

**b69. Re-run the eval with replay and memory switched on**

Runs the same evaluation again with the stretch features switched on.

- Same traffic and faults as e1
- Replay and memory enabled by configuration
- Triage the last window a second time to measure duplicates
- **Done when:** A second results table exists for the same faults.

**b70. Compare duplicate and false-positive rates with the MVP run**

Shows what replay and memory actually bought.

- Table of duplicate rate and false positives before and after
- Also report the change in cost and time
- Write down what did not improve
- **Done when:** A before and after comparison is recorded.

### Deploy, README and demo

- **Wave:** 5 · **Tier:** Ship
- **Owns:** deploy/, README.md
- **Goal:** Package, deploy (or prepare a recorded run), document and record the three-minute demo.
- **Builds against:** Baseline, thresholds and MVP gate (g1); Project decisions (d3); Trace viewer UI (f7)
- **Done when:** A viewer can follow the README, and the demo is recorded.

| Card | Area | Task | Needs |
|---|---|---|---|
| b77 | backend | Package the collector, database and MCP server to run together | g1* |
| b78 | backend | Deploy the backend services (Skip if the demo is recorded.) | b77, d3* |
| f15 | frontend | Deploy the trace viewer (Skip if the demo is recorded.) | f7*, b78, d3* |
| s3 | shared | Write the README | g1* |
| s4 | shared | Record the three-minute demo | s3, d3* |

#### Card details: Deploy, README and demo

**b77. Package the collector, database and MCP server to run together**

Packages the backend so it starts with one command.

- Container setup for the collector, Postgres and the MCP server
- Example environment file and a health check for each service
- **Done when:** One command starts all backend services on a clean machine.

**b78. Deploy the backend services**

Puts the backend on a host. Skip if the demo is recorded.

- Pick a host (TBD)
- Set environment values and the database
- Serve the collector over HTTPS and run a smoke test
- **Done when:** Medas traces reach the hosted collector.
- **Open point:** Skip if the demo is recorded.

**f15. Deploy the trace viewer**

Puts the trace viewer on a host. Skip if the demo is recorded.

- Deploy the app with the API URL set to the hosted backend
- Smoke test on real traces
- **Done when:** The hosted viewer shows real traces.
- **Open point:** Skip if the demo is recorded.

**s3. Write the README**

The document a viewer reads first.

- What it is and why, with an architecture diagram
- How to run it and how to run the evaluation
- The results table
- Limits, what is stubbed and what is dry run
- **Done when:** A new reader can follow it from clone to a dry-run result.

**s4. Record the three-minute demo**

The three-minute demonstration.

- Script: turn a fault on, see the traces in the viewer, run triage, review, show the dry-run issue and the metrics
- Rehearse, then record
- **Done when:** A recording of three minutes or less exists.

