// Per-card description (d), concrete details (how) and done-when (ok), keyed by card id.
// Anything the source document does not define is marked "proposed" or "TBD".
// Used by build-board.js, which fails if a card has no entry or an entry has no card.
const D = {};
const add = (id, d, how, ok) => { D[id] = { d, how, ok }; };

// ---- Project decisions ----
add('d1',
  "The PRD asks whether building a custom tracing stack (collector, store, viewer) is a good use of capstone time compared with a platform such as Langfuse. The architecture assumes custom, so this answer sets the size of milestone 1.",
  ["Compare the effort of the collector, scoring and viewer with adopting a platform and reading traces from its API",
   "Check whether the course expects you to build the tracing path yourself",
   "Write the answer and the reason under Open Questions in the PRD"],
  "The decision is written in the PRD. If the answer is not custom, the collector, trace API and viewer cards need to be reworked.");
add('d2',
  "Medas is clinician-facing, so its traces may hold clinical content. The decision sets what is stored, what is redacted and what may appear in a GitHub issue.",
  ["Find out whether Medas questions, retrieved passages or answers can contain patient data",
   "Pick one approach: store metadata only, redact before storing, or store everything in a private database",
   "Decide what the issue body and regression test may quote",
   "Write the decision in the PRD"],
  "A written rule exists that the collector (b5), Medas instrumentation (b6) and issue drafting (b30) can follow.");
add('d4',
  "The PRD asks whether fault injection alone is a strong enough evaluation, since the author injects the bugs and also built the agent. Adding the MAST-Data comparison brings in an outside benchmark.",
  ["Weigh fault injection alone against adding a published benchmark",
   "Estimate the effort of cards b71 to b74 against the day 10 deadline",
   "Record yes or no in the PRD"],
  "A yes or no is recorded. If yes, the MAST-Data cards move into milestone 4.");
add('d3',
  "The course may require a live deployed demo or accept a recorded one. The answer decides whether the two deploy cards are needed.",
  ["Check the course brief or ask the instructor",
   "If a recording is enough, the deploy cards b78 and f15 are skipped",
   "Record the answer in the PRD"],
  "The demo format is recorded in the PRD.");

// ---- Contracts and fixtures ----
add('b1',
  "The storage schema that every other part reads or writes. It is the first contract, so the collector, the viewer API and the MCP server can be built in parallel.",
  ["traces table: id, start time, end time, root span name, status",
   "spans table: id, trace id, parent span id, name, kind, start, end, status, attributes as JSON",
   "Indexes on trace start time and on the trace id of spans",
   "Ship it as a migration file under contracts/. Do not store the injected fault name on any row, so the agent cannot read the answer"],
  "The migration applies to an empty Postgres database and the tables accept the fixture rows from c4.");
add('b2',
  "Stores the result of scoring, so the viewer, the API and the agent can filter failed and low-quality traces.",
  ["scores table: trace id, label (ok, error, timeout, low_quality), numeric value, source (rule or model), created time",
   "One trace can have several scores",
   "Foreign key to traces; migration sits next to b1"],
  "The migration applies cleanly and a score row cannot point at a missing trace.");
add('b20',
  "The fixed list of failure categories a diagnosis must choose from. The source names the six faults but does not list categories, so this card sets them.",
  ["Proposed starting point: one category per injected fault (empty retrieval, tool schema error, truncated prompt, context overflow, weaker-model quality drop, upstream timeout) plus other",
   "Write a one-line definition and the span evidence that signals each category",
   "Store it as a JSON or enum file in contracts/ that b21, b48, b59 and b72 import",
   "Trade-off to record: mirroring the faults one to one makes root-cause accuracy easy to score and weaker as evidence"],
  "The author has reviewed the taxonomy and every injected fault maps to exactly one category.");
add('b21',
  "The structured output of a diagnosis. The model must fill this shape, and later nodes and metrics read it.",
  ["Pydantic model with category (from b20), cause in plain text, suggested fix, cited span ids and cluster id",
   "Proposed extra field: confidence",
   "Validation: category must be in the taxonomy and at least one span must be cited",
   "Used as the structured-output schema in b27"],
  "Valid and invalid examples are both covered by tests.");
add('c7',
  "Names the attributes written on retrieval, model-call, tool-call and error spans. Medas writes them, the collector stores them and the agent reads them, so they must be fixed first.",
  ["Retrieval: query, result count, top similarity score. Model call: model name, prompt tokens, completion tokens, context limit, finish reason. Tool call: tool name, arguments, error. Error: type, message, timeout flag",
   "Follow OpenTelemetry GenAI semantic conventions where a name already exists; put the rest under a project prefix such as tracescan.",
   "Mark which attributes can carry free text, so the outcome of d2 can be applied to them"],
  "A single table in contracts/ (attribute, span kind, type, example, may hold free text) that Medas, the collector and the agent all cite.");
add('c1',
  "The contract for the trace API, written before the API exists so the viewer and its mock can be built at the same time as the collector.",
  ["GET /traces with from, to, failed_only, limit and cursor parameters, returning trace summaries with status and score",
   "GET /traces/{id} returning the trace and its spans with parent links",
   "One error shape and one pagination scheme",
   "Include example responses. The fixtures in c4 must validate against them"],
  "An OpenAPI 3.1 file in contracts/ that passes a validator and has examples for both endpoints.");
add('c2',
  "The contract for the two read-only tools the agent uses to read traces. The agent and the MCP server are built against this, not against each other.",
  ["Tool one: list failed and low-score traces for a time window",
   "Tool two: get one trace with its spans",
   "Inputs and outputs as JSON schemas, matching the trace API shapes where possible",
   "State the limits: maximum traces per call and how long text fields are truncated"],
  "JSON schemas in contracts/ for both tools, with example calls and results.");
add('c3',
  "The shared Python models that the analysis nodes, the review nodes and the metrics all pass around. Without them each feature would invent its own shapes.",
  ["Graph state: time window, trace ids, clusters, diagnoses, proposals, decisions, run summary",
   "Proposal: type (create or update, proposed), title, body, regression test case, cited traces",
   "Review decision: proposal id, approve or reject, optional note",
   "Run summary: counts, token cost, wall-clock time"],
  "Models import cleanly, round-trip to JSON, and are used by the fixtures in c6.");
add('c4',
  "Synthetic failed traces in the stored format. They let every other feature develop and test without the real collector or Medas.",
  ["Three to five failed traces per injected fault, plus healthy traces and a few unrelated failures as noise",
   "Plain JSON, with the expected score and expected category recorded in a separate file used only by tests and metrics",
   "No real clinical text"],
  "Fixtures validate against b1, c1 and c2, and the expected-category file covers every failed trace.");
add('c5',
  "Loads the fixture traces into a local Postgres so the MCP server can be tested against a real database.",
  ["Applies the b1 and b2 migrations if needed, then inserts the c4 fixtures",
   "Idempotent: running it twice does not duplicate rows",
   "Takes the database URL as an argument and prints how many traces and spans were loaded"],
  "After the script runs, the MCP tools b18 and b19 can be tested against that database.");
add('c6',
  "Fixture proposals and review decisions, so the review and action nodes can be tested without the analysis nodes.",
  ["A handful of proposals in the c3 shape, each with a regression test case",
   "Decision sets: all approved, all rejected, mixed, and none",
   "The expected dry-run output for each decision set"],
  "Fixtures load through the c3 models and each decision set has an expected output.");
add('b22',
  "The empty shell of the triage graph. It fixes the state and the entry point so the analysis and review features can each fill in their own nodes.",
  ["LangGraph StateGraph using the c3 state, with the eight node names registered as stubs",
   "Entry point: run triage with a start time, an end time and a dry-run flag that defaults to on",
   "Returns the run summary; no node logic yet"],
  "The skeleton runs end to end with stubs and returns an empty run summary.");

// ---- Trace collector and API ----
add('b3',
  "The front door of the tracing path: an HTTP endpoint that accepts OpenTelemetry exports from Medas.",
  ["FastAPI endpoint for OTLP over HTTP (protobuf; JSON optional)",
   "Return success once the batch is accepted and 400 for a malformed payload",
   "Configuration through environment variables; no authentication in the MVP because it runs locally (proposed)"],
  "A sample OTLP export posted with curl returns success.");
add('b4',
  "Turns accepted exports into rows in the b1 tables.",
  ["Map OTLP resource spans to trace and span rows",
   "Keep trace id, span id and parent span id; attributes go in the JSON column",
   "Handle spans that arrive out of order or twice"],
  "A multi-span sample export produces correct parent links and no duplicate rows when sent twice.");
add('b5',
  "Applies the sensitive-data decision before anything is stored.",
  ["Drop, hash or mask the attributes flagged in c7, following d2",
   "Keep the list of fields in configuration so it can change without code changes",
   "Test with a fixture that holds fake patient-like text"],
  "Flagged content never reaches the database.");
add('b11',
  "The first part of scoring: a rule-based pass that marks traces with errors or timeouts.",
  ["Run after spans are stored; mark a trace failed when any span has an error status or the timeout flag",
   "Write a row to the scores table with label error or timeout and source rule",
   "Safe to run again on the same trace"],
  "Fixture traces with errors and timeouts are labelled, healthy ones are not, and a rerun adds no duplicate scores.");
add('b12',
  "The second part of scoring: marking answers that finished without errors but are poor. The source asks for low-score traces but does not say how to score them.",
  ["Decide the method first. Options: an LLM judge with a rubric, or a simple heuristic such as an empty or very short answer",
   "Record the method and its known weaknesses in the PRD metrics section",
   "Write a low_quality score with the numeric value"],
  "The method is recorded, known-bad fixture answers are flagged and known-good ones are not.");
add('b15',
  "The list endpoint of the trace API, used by the viewer.",
  ["GET /traces implementing c1",
   "Filters: from, to and failed_only; newest first; cursor pagination",
   "Response validated against the OpenAPI file in tests"],
  "Responses match c1 on seeded data, and the filters return the expected traces.");
add('b16',
  "The detail endpoint of the trace API, used by the viewer.",
  ["GET /traces/{id} returning the trace header, its score and all spans with parent links",
   "404 for an unknown id",
   "Response validated against c1"],
  "A seeded trace returns every span with correct parent links.");

// ---- Medas instrumentation and fault injection ----
add('b13',
  "The questions the traffic generator sends to Medas. They must exercise each injected fault, or the fault will leave no trace.",
  ["Write 10 to 20 questions covering the topics Medas handles",
   "Include questions that need retrieval, questions that need a tool and questions that need long context",
   "Keep them in a plain file that the traffic generator reads",
   "Use no real patient data"],
  "The set contains at least a few questions that each fault should break.");
add('b6',
  "Start of instrumentation: OpenTelemetry in Medas with one root span per request.",
  ["Add the OpenTelemetry SDK and an OTLP HTTP exporter pointed at the collector",
   "One root span per user request, with the request id and the outcome",
   "Apply the d2 decision to any text put on a span",
   "Use the attribute names from c7"],
  "A request to Medas produces one exported root span.");
add('b7',
  "Retrieval spans, so the agent can see what the search step returned.",
  ["Child span of the root for each retrieval",
   "Attributes from c7: query text (subject to d2), result count, top similarity score"],
  "A request that retrieves shows a retrieval span with the result count.");
add('b8',
  "Model-call spans, so the agent can see which model ran and how much context it had.",
  ["Child span for each model call",
   "Attributes from c7: model name, prompt tokens, completion tokens, context limit, finish reason"],
  "Every model call shows its model name and token counts.");
add('b9',
  "Tool-call spans, so the agent can see which tool was called and whether it failed.",
  ["Child span for each tool call",
   "Attributes from c7: tool name, arguments, result size, error"],
  "A tool call shows its name and arguments, and a failing call shows its error.");
add('b10',
  "Makes sure failures and timeouts are recorded on the spans, since the agent can only diagnose what it can see.",
  ["Set the span status to error and attach the exception type and message",
   "Mark timeouts with the timeout flag from c7",
   "Cover failures from the model provider, the tools and retrieval"],
  "A forced timeout and a forced exception each show up on the right span.");
add('b14',
  "Sends the question set to Medas at a set rate, so each fault run produces enough traffic to cluster.",
  ["Script that reads the b13 questions and sends them at a configurable rate and duration",
   "Give each run an opaque run id. Write the run id and active fault to a separate ground-truth file, never onto spans",
   "Report how many requests succeeded and how many failed"],
  "A run produces traces in the collector and the ground-truth file lists the run id.");
add('b41',
  "The switch that turns exactly one fault on, so each eval run has a known cause.",
  ["One setting (an environment variable, proposed) names the active fault; unset means healthy",
   "Refuse to start when more than one fault is selected",
   "Write the active fault to the run log, not to span attributes"],
  "Each of the six values selects its fault and a healthy run is possible.");
add('b42',
  "Injected fault 1 of 6: the retrieval step returns nothing.",
  ["When on, the retrieval step returns no results",
   "Expected signal: retrieval spans with result count 0, and answers that have no support"],
  "With the fault on, retrieval spans show zero results and answers are unsupported.");
add('b43',
  "Injected fault 2 of 6: a tool schema that no longer matches what the tool accepts.",
  ["When on, a tool is declared with a schema that does not match its real inputs",
   "Expected signal: tool-call spans with validation errors"],
  "With the fault on, calls to that tool fail with a schema error.");
add('b44',
  "Injected fault 3 of 6: the system prompt is cut short.",
  ["When on, truncate the system prompt, for example to half its length",
   "Expected signal: a smaller prompt token count and answers that ignore the cut rules"],
  "With the fault on, model-call spans show a smaller prompt than in a healthy run.");
add('b45',
  "Injected fault 4 of 6: a context window too small for the input.",
  ["When on, limit the context so retrieved passages or history are dropped",
   "Expected signal: context limit reached, a finish reason of length, or missing passages"],
  "With the fault on, model-call spans show the reduced limit.");
add('b46',
  "Injected fault 5 of 6: a weaker model replaces the normal one.",
  ["When on, switch model calls to a smaller model",
   "Expected signal: a different model name and lower answer quality with no errors. This is the hardest fault for rule-based scoring and depends on b12"],
  "With the fault on, model-call spans show the weaker model.");
add('b47',
  "Injected fault 6 of 6: upstream timeouts.",
  ["When on, make a dependency (the model provider or a tool) slow or time out for a share of requests",
   "Expected signal: timeout-flagged spans on part of the traffic"],
  "With the fault on, a share of requests ends in recorded timeouts.");

// ---- Read-only MCP server ----
add('b17',
  "The MCP server shell. The agent can only read traces through it, and the database itself enforces that it cannot write.",
  ["FastMCP server using the c2 contract",
   "Connects to Postgres with a role granted SELECT only on the trace tables",
   "A test shows that an insert through this connection is rejected by the database"],
  "The server starts, lists its two tools and cannot write.");
add('b18',
  "The tool that lists failed and low-score traces for a time window. It is the agent's way in.",
  ["Inputs: window start, window end and an optional limit",
   "Returns traces that are failed or have a low_quality score, with summary fields only",
   "Tested against a database seeded by c5"],
  "Returns exactly the failed and low-score fixture traces inside the window.");
add('b19',
  "The tool that returns one trace with all its spans, for diagnosis.",
  ["Input: trace id; output: the trace with every span",
   "Truncate very long text fields and say so in the output, as defined in c2",
   "Return a clear error for an unknown id"],
  "Returns a full fixture trace and an error for a missing one.");

// ---- Trace viewer UI ----
add('f1',
  "The empty app: page layout and navigation, so every other UI card has somewhere to live.",
  ["Next.js app with TypeScript and a runs page route",
   "Layout with header and navigation",
   "API base URL read from an environment variable, so the mock and the real API can be swapped"],
  "The app starts and shows the layout with a placeholder runs page.");
add('m1',
  "A small server that behaves like the trace API, so the UI can be built before the collector exists.",
  ["Implements the c1 contract and serves the c4 fixtures",
   "Supports the same filters as the real API",
   "Used for development only"],
  "The UI can list and open fixture traces with no other service running.");
add('f2',
  "The first page a user sees: all runs in a table.",
  ["Columns: time, root span name, duration, status and score",
   "Loading, empty and error states",
   "Each row links to the trace detail page"],
  "The table shows every fixture trace and each row opens the detail page.");
add('f3',
  "Lets the user narrow the list to the window and the failures they care about.",
  ["Time window picker with presets (last hour, last 24 hours) and a custom range",
   "Failed-only toggle",
   "Keep the filters in the URL so a view can be shared"],
  "Changing a filter changes the list and survives a page reload.");
add('f4',
  "The top of a trace's page: the facts about the whole run.",
  ["Show trace id, start time, total duration, status and score",
   "A not-found state for an unknown id"],
  "A fixture trace shows the right header and an unknown id shows not found.");
add('f5',
  "Shows how a request unfolded, step by step.",
  ["Spans nested by parent",
   "Each row shows span name, kind and duration, with a bar sized against the trace duration",
   "Expand and collapse"],
  "The tree for a fixture trace matches its parent links.");
add('f6',
  "The panel where a person reads the evidence in one span.",
  ["Click a span to open its attributes, inputs, outputs and error message",
   "Long text collapses",
   "Content may be sensitive, so follow d2"],
  "Selecting a span shows all its stored fields, including an error when there is one.");
add('f7',
  "Makes failed and low-score runs easy to spot.",
  ["Badges for Failed, Timeout and Low score",
   "Shown on list rows, in the detail header and on spans with errors",
   "Use text as well as colour"],
  "A failed fixture shows its badge on the list and the detail page.");

// ---- Triage analysis nodes ----
add('a1',
  "A stand-in for the real MCP client. It lets the analysis nodes run with no database and no server.",
  ["Same interface the real client will have: list failed traces for a window, get one trace",
   "Reads the c4 fixtures and returns the c2 shapes",
   "Switched to the real client by configuration in i3"],
  "The nodes can be tested end to end with this client alone.");
add('b23',
  "First node of the graph: gathers the failed traces for the run's window.",
  ["Call the list tool for the window, then the get tool for each trace",
   "Cap the number of traces per run (proposed) and note when the cap is hit",
   "Put the full traces into graph state"],
  "With the stub client, state holds every failed fixture trace.");
add('b24',
  "Prepares traces for clustering by turning each into a short text and a vector.",
  ["Build a short text per trace: failing span name, error message and key attributes, trimmed to a size limit",
   "Embed with an embedding model (the choice is TBD; record its cost)",
   "Cache embeddings by trace id"],
  "Each failed trace has a text and a vector of the same size.");
add('b25',
  "Groups similar failures so one issue can be drafted per cause rather than per trace.",
  ["Run HDBSCAN on the vectors; label -1 is noise and is kept apart, not forced into a cluster",
   "min_cluster_size is a parameter. With 3 to 5 traces per fault in the fixtures, expect a small value (starting value TBD; tune on the fixtures)",
   "Output clusters with their trace ids"],
  "On the fixtures, traces for the same fault land in the same cluster.");
add('b26',
  "Handles the case where there is nothing to diagnose.",
  ["Conditional edge: zero clusters goes to the end of the graph",
   "The run summary states that no clusters were found and how many traces were noise",
   "No review step starts"],
  "A run over healthy fixtures ends cleanly with that message.");
add('b27',
  "The diagnosing step: one model call that explains a cluster.",
  ["Give the model a sample of traces from the cluster, with spans trimmed",
   "Ask for the b21 model as structured output",
   "The prompt lists the b20 categories with their definitions",
   "Record the tokens used, for b32"],
  "Each fixture cluster returns a valid diagnosis; invalid output is retried once (proposed).");
add('b28',
  "Diagnoses all clusters at the same time.",
  ["Use LangGraph Send to start one diagnose branch per cluster",
   "Collect the results back into state in a stable order",
   "A failing branch is recorded and does not stop the others"],
  "Three clusters produce three diagnoses and one forced failure leaves the other two intact.");
add('b29',
  "A guard against made-up evidence: every span a diagnosis cites must really be in its cluster.",
  ["Deterministic check, no model call",
   "On failure, retry the diagnosis once, then drop it and note this in the run summary (proposed)"],
  "A diagnosis that cites an unknown span is rejected.");
add('b30',
  "Turns a checked diagnosis into the issue a person will review.",
  ["Short, specific title",
   "Body: summary, cause, evidence (trace and span ids), suggested fix and the number of affected traces",
   "Follow d2 on what content may be quoted"],
  "Each fixture diagnosis gives a proposal that a reviewer can understand without opening the code.");
add('b31',
  "Adds the regression test that makes the fix checkable.",
  ["Take the failing input and the expected correct behaviour from the diagnosis",
   "Output a case record that can be appended to an eval dataset (format defined in c3)",
   "Readable without opening the trace"],
  "Each proposal carries a regression case that matches its diagnosis.");
add('b32',
  "Measures what a run costs, since cost and time per run are two of the success metrics.",
  ["Sum token usage over every model and embedding call in the run",
   "Convert to cost with a price table in configuration",
   "Record wall-clock time per node and in total, and write both to the run summary"],
  "The run summary shows cost and time for a fixture run.");

// ---- Human review and dry-run actions ----
add('b33',
  "Lets a run stop and be resumed later, which human review needs.",
  ["Postgres checkpointer for the graph",
   "One thread id per run",
   "State is saved after each step"],
  "Stop the process mid-run, restart it and resume from the saved state.");
add('b34',
  "The pause point where the agent hands its proposals to a person.",
  ["The human_review node calls interrupt() with the proposals",
   "Nothing after this node runs until a decision arrives"],
  "A run over the c6 fixture proposals stops here and reports that it is waiting.");
add('b35',
  "A terminal review, since the review dashboard is stretch.",
  ["A command that lists runs waiting for review",
   "Shows each proposal with its title, body and regression test",
   "Collects approve or reject for each proposal, with an optional note",
   "Shows a summary before submitting"],
  "A person can review a fixture run in the terminal and get a decision list.");
add('b36',
  "Resumes the paused run with the person's decisions.",
  ["Resume the graph with the decision list",
   "If every proposal is rejected, end the run without calling apply_actions",
   "Reject an incomplete list: every proposal needs a decision"],
  "Approved decisions continue to apply_actions and all-rejected ends the run.");
add('b37',
  "The action step. It is where the human gate becomes real: only approved proposals pass.",
  ["Loop over approved proposals only",
   "Send each to the writer chosen by the dry-run flag",
   "Test with a fake writer"],
  "Rejected proposals produce no output in any mode.");
add('b38',
  "The safety switch: nothing is sent to the outside world unless this is turned off.",
  ["Flag in configuration and on the command line, default on",
   "Every real-write path must check it",
   "The run summary states whether the run was a dry run"],
  "A run with no flag set behaves as a dry run.");
add('b39',
  "What dry run does for an issue: write it to a local file instead of GitHub.",
  ["One markdown file per approved issue, in an output folder",
   "File name from the proposal id; the content is the issue title and body",
   "Do not overwrite existing files by accident (proposed)"],
  "Approving a fixture proposal creates a readable issue file.");
add('b40',
  "What dry run does for a regression test: write it to a local eval dataset.",
  ["Append one JSON line per approved regression case to a dataset file",
   "Skip a case already present, keyed by proposal id"],
  "Approving a fixture proposal adds exactly one line to the dataset, and approving it again adds none.");

// ---- Eval ground truth and metrics ----
add('b48',
  "The answer key for the evaluation: what each injected fault should be diagnosed as.",
  ["Six rows: fault name, expected category (from b20) and the span signal that should appear",
   "Stored in eval/ and kept where the agent cannot read it"],
  "Every fault has one expected category.");
add('b50',
  "Metric 1: how many of the injected faults TraceScan found.",
  ["Proposed definition: a fault is detected when at least one proposal matches its expected category. Rate = detected faults divided by 6",
   "Test on fixture results with known outcomes"],
  "Returns the expected value on a hand-made result set.");
add('b51',
  "Metric 2: of the faults found, how often the diagnosis names the right cause.",
  ["Proposed definition: among detected faults, the share whose diagnosed category equals the ground-truth category",
   "Test with a result set that has one wrong category"],
  "Returns the expected value on a hand-made result set.");
add('b52',
  "Metric 3: reported issues that match no injected fault.",
  ["Proposed definition: proposals whose category and traces match no fault, as a count and as a share of all proposals",
   "Includes proposals from a healthy run"],
  "Returns the expected value on a hand-made result set.");
add('b53',
  "Metric 4: repeat issues when the same traffic is triaged twice.",
  ["Run the same window twice; count proposals in the second run that repeat one from the first",
   "In the MVP this is the baseline. It should fall to 0 once known-issues memory exists"],
  "Returns the expected value on a hand-made pair of runs.");
add('b54',
  "Metrics 5 and 6: spend and wall-clock time per run.",
  ["Read cost and time from each run summary (b32)",
   "Report per fault, mean and total"],
  "Returns the expected values on fixture run summaries.");
add('b55',
  "The evaluation output: one table with all metrics.",
  ["One row per fault; columns for each metric",
   "Written as markdown and CSV in eval/results/",
   "Includes the run date and the configuration used"],
  "A table is produced from fixture results with every metric filled in.");

// ---- MVP integration and eval run ----
add('i1',
  "First real join: Medas spans reach the real collector.",
  ["Run Medas with the exporter pointed at the collector and send a short batch with b14",
   "Check traces and spans exist with correct parent links",
   "Report any mismatch with c7 to the lead; contracts change only through the lead"],
  "A Medas request is stored and its span tree is complete.");
add('i2',
  "Second real join: the viewer reads real data.",
  ["Point the API base URL at the real trace API instead of the mock",
   "Click through list, filters, detail, span tree and span panel on real traces",
   "List any field the mock had that the API lacks"],
  "The viewer works on traces that Medas produced.");
add('i4',
  "Joins the analysis and review parts and checks them together on fixtures.",
  ["Connect the nodes in order: collect, cluster, diagnose in parallel, draft, human review, apply. The replay and match nodes stay as pass-through for the MVP",
   "Run with the stub client and fixture decisions",
   "Check the run summary and the output files"],
  "A fixture run goes from window to dry-run files through the one graph.");
add('i3',
  "Third real join: the graph runs on real Medas traces.",
  ["Switch the MCP client from the stub to the real server",
   "Run on traces from a faulty Medas run",
   "Check that clusters, diagnoses and proposals look sensible, review in the terminal and check the dry-run files"],
  "One full run on real traces ends in dry-run output.");
add('b49',
  "Automates the evaluation, so every fault is tested the same way.",
  ["For each of the six faults: turn the fault on, generate traffic with b14, wait for collection and scoring, run TraceScan on that window, and save the run summary and proposals",
   "Add a healthy run to count false positives (proposed)",
   "Triage the last window a second time to measure duplicates",
   "Eval runs approve proposals automatically, with dry run on, so no person is needed (proposed)"],
  "One command runs all faults and leaves the raw results on disk.");
add('e1',
  "The evaluation itself: the numbers the MVP gate is judged on.",
  ["Run b49 over all faults, compute b50 to b54 and write the b55 table",
   "Keep the raw run summaries next to the table",
   "Note any run that failed and why"],
  "A results table exists for all six faults.");

// ---- Baseline, thresholds and MVP gate ----
add('s1',
  "Gives the PRD its missing evidence: how long finding the cause by hand takes today.",
  ["Pick one faulty run",
   "Open the traces in the viewer and find the pattern by hand",
   "Time it from start to written diagnosis, and write the time and the diagnosis in the PRD Evidence section"],
  "The PRD holds a measured manual time.");
add('s2',
  "Replaces the TBD targets in the PRD with numbers.",
  ["Read the e1 results and the s1 baseline",
   "Set a target for each metric in the Success Metrics table",
   "State what counts as failing"],
  "No metric in the PRD is left as TBD for the MVP.");
add('g1',
  "The day 10 checkpoint. It decides whether stretch work goes ahead.",
  ["Compare milestones 1 to 4 with their outcomes in the PRD",
   "If behind, name the stretch milestones that are cut",
   "Update milestone status in the PRD"],
  "A go or cut decision is written down for each stretch feature.");

// ---- Replay reproduction (stretch) ----
add('b56',
  "A way to run Medas again on a given input, so a diagnosis can be tested.",
  ["Endpoint in Medas that takes a question and the fault settings and returns the answer and a trace id",
   "Local only, and it must not touch production data (proposed)"],
  "A call returns an answer and the trace of that call.");
add('b57',
  "Picks what to replay for each cluster.",
  ["From a cluster's traces take the original user input and any parameters needed",
   "Choose a few representative inputs and remove duplicates"],
  "Each fixture cluster yields its replay inputs.");
add('b58',
  "Tries the failure again for each diagnosis, at the same time.",
  ["Use LangGraph Send: one replay per cluster",
   "Call the b56 endpoint and collect the output and the new trace"],
  "Each cluster comes back with its replay results.");
add('b59',
  "Decides what counts as reproduced. The source does not define this.",
  ["Write one rule per taxonomy category using span evidence, for example: empty retrieval is reproduced when the replay again returns zero results",
   "Model output varies, so decide whether to replay each input several times (TBD)",
   "Keep the rules as code with tests on fixture replays"],
  "Reproduced and unreproduced fixtures are told apart.");
add('b60',
  "Stops unconfirmed causes from reaching a reviewer.",
  ["Remove clusters marked not reproduced before proposals are drafted",
   "List the dropped clusters and the reason in the run summary"],
  "An unreproduced fixture cluster produces no proposal.");

// ---- Known-issues memory (stretch) ----
add('b61',
  "The long-term store of issues from earlier runs.",
  ["Fields: id, category, summary, embedding or cluster signature, first seen, last seen, occurrence count, link (file path or issue URL), status",
   "Migration"],
  "The migration applies and rows can be stored and read.");
add('b62',
  "Remembers what was filed.",
  ["After a proposal is applied, insert a row",
   "Do this in dry run too, so the duplicate metric can be measured (proposed)"],
  "Applying a fixture proposal adds one known-issue row.");
add('b63',
  "Recognises a failure seen before.",
  ["Compare the cluster with stored issues by embedding similarity",
   "Return the closest match above a threshold, or none (threshold TBD; tune on fixtures)"],
  "A repeat fixture cluster matches its stored issue and a new one does not.");
add('b64',
  "Adds a second kind of proposal: update an existing issue instead of opening a new one.",
  ["When a match exists, draft an update that adds the new occurrences and evidence",
   "Reviewer sees which issue it would update"],
  "A matched cluster produces an update proposal.");
add('b65',
  "Carries out an update in dry run.",
  ["For an update proposal, append to the existing issue file and raise the occurrence count",
   "Do not create a new file"],
  "A second run over the same traffic produces updates and no new issues.");

// ---- GitHub issues (stretch) ----
add('b66',
  "First real write: create an issue on GitHub.",
  ["Use the GitHub REST API with a token from the environment; repository from configuration",
   "Create the issue with title, body and a tracescan label",
   "Return the issue URL and store it with the known issue",
   "Never log the token"],
  "An approved proposal becomes an issue in a test repository.");
add('b67',
  "Update an issue that already exists.",
  ["Add a comment or edit the body of the stored issue",
   "Find the issue through the URL stored in the known-issues table"],
  "An update proposal changes the right issue.");
add('b68',
  "The guard that keeps GitHub writes behind dry run.",
  ["Route every write through one function that checks the dry-run flag",
   "Test that with dry run on no network call is made"],
  "With dry run on nothing is sent, and with it off a write is made.");

// ---- Review dashboard (stretch) ----
add('c8',
  "The contract between the dashboard and its API, so both can be built at once.",
  ["List runs waiting for review, with proposals and evidence trace ids",
   "Submit decisions",
   "Return the apply result (file path or issue URL)",
   "OpenAPI, as in c1"],
  "An OpenAPI file with examples.");
add('b75',
  "The read side of review.",
  ["Endpoint listing runs waiting for review",
   "Each run includes its proposals and cited traces"],
  "Returns the runs that are paused in a seeded test.");
add('b76',
  "The write side of review: decisions come in and the run resumes.",
  ["Endpoint that takes a decision list and resumes the run using the b36 logic",
   "Return the apply result",
   "Reject a run that has already been decided"],
  "A submitted decision list resumes the run and returns its outcome.");
add('f8',
  "The first dashboard page: runs that need a decision.",
  ["List of runs waiting for review",
   "Built against a mock of the c8 API",
   "Empty, loading and error states"],
  "The page lists the mocked runs.");
add('f9',
  "How one proposal reads.",
  ["Title, body rendered as markdown and the regression test in a code block",
   "Shows which traces it is based on"],
  "A mocked proposal shows all three parts.");
add('f10',
  "Lets the reviewer check the evidence before deciding.",
  ["List the cluster's traces",
   "Each links to the trace viewer, and to the cited span when there is one"],
  "Each evidence link opens the right trace.");
add('f11',
  "Shows whether a failure was reproduced, once replay exists.",
  ["Show a reproduced or not reproduced badge only when the data is present",
   "Hidden otherwise"],
  "A proposal with replay data shows the badge and one without shows none.");
add('f12',
  "The decision controls.",
  ["Approve and reject buttons on each proposal, with an optional note",
   "State is kept per proposal and can be changed before submitting"],
  "Each proposal can be approved, rejected or changed back.");
add('f13',
  "Sends the decisions and resumes the run.",
  ["Submit is disabled until every proposal has a decision",
   "Confirm step, loading and error states",
   "Calls the review API and shows that the run resumed"],
  "A complete set of decisions can be submitted to the mock.");
add('f14',
  "Shows what happened after approval.",
  ["For each approved proposal show the dry-run file path or the GitHub issue link",
   "Rejected proposals show as rejected"],
  "The result view matches the submitted decisions.");
add('i5',
  "Last dashboard join: the real review API.",
  ["Switch from the mock to the real API",
   "Approve one proposal end to end and check the dry-run output"],
  "A person can review and resume a real paused run in the browser.");

// ---- MAST-Data benchmark (stretch) ----
add('b71',
  "Brings in the outside benchmark traces.",
  ["Check the dataset format and licence first",
   "Convert each trajectory to the stored trace format, or to text the diagnoser accepts",
   "Use a sample size you can afford (cost TBD)"],
  "The chosen sample loads and each item has its human label.");
add('b72',
  "Makes the benchmark's labels comparable with the failure taxonomy.",
  ["Write a mapping table from each benchmark label to a taxonomy category, or to unmapped",
   "Taxonomy changes go through the lead",
   "Report how many labels could not be mapped"],
  "Every benchmark label has a mapping or is marked unmapped.");
add('b73',
  "Runs the agent's diagnosis on the benchmark.",
  ["Reuse the diagnose step on each benchmark item",
   "Record the predicted category and the tokens used"],
  "Each sampled item has a predicted category.");
add('b74',
  "The result: how well the agent agrees with human labels.",
  ["Report the agreement rate, with a breakdown by label",
   "Compare with a simple baseline such as always guessing the most common label (proposed)"],
  "An agreement figure is written next to the baseline.");

// ---- Stretch evaluation rerun ----
add('b69',
  "Runs the same evaluation again with the stretch features switched on.",
  ["Same traffic and faults as e1",
   "Replay and memory enabled by configuration",
   "Triage the last window a second time to measure duplicates"],
  "A second results table exists for the same faults.");
add('b70',
  "Shows what replay and memory actually bought.",
  ["Table of duplicate rate and false positives before and after",
   "Also report the change in cost and time",
   "Write down what did not improve"],
  "A before and after comparison is recorded.");

// ---- Deploy, README and demo ----
add('b77',
  "Packages the backend so it starts with one command.",
  ["Container setup for the collector, Postgres and the MCP server",
   "Example environment file and a health check for each service"],
  "One command starts all backend services on a clean machine.");
add('b78',
  "Puts the backend on a host. Skip if the demo is recorded.",
  ["Pick a host (TBD)",
   "Set environment values and the database",
   "Serve the collector over HTTPS and run a smoke test"],
  "Medas traces reach the hosted collector.");
add('f15',
  "Puts the trace viewer on a host. Skip if the demo is recorded.",
  ["Deploy the app with the API URL set to the hosted backend",
   "Smoke test on real traces"],
  "The hosted viewer shows real traces.");
add('s3',
  "The document a viewer reads first.",
  ["What it is and why, with an architecture diagram",
   "How to run it and how to run the evaluation",
   "The results table",
   "Limits, what is stubbed and what is dry run"],
  "A new reader can follow it from clone to a dry-run result.");
add('s4',
  "The three-minute demonstration.",
  ["Script: turn a fault on, see the traces in the viewer, run triage, review, show the dry-run issue and the metrics",
   "Rehearse, then record"],
  "A recording of three minutes or less exists.");

module.exports = D;
