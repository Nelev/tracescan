// Single source for the TraceScan cards. Usage: node build-board.js <board.html> <work-packages.md>
// Regenerates the data block inside the board page and writes the subagent work-packages brief.
const fs = require('fs');
const [HTML, MD] = process.argv.slice(2);

const MS = {
  1:{name:'Medas traces visible', days:'Days 1-4', tier:'mvp'},
  2:{name:'Triage report on Medas', days:'Days 4-8', tier:'mvp'},
  3:{name:'Human-gated actions', days:'Days 8-9', tier:'mvp'},
  4:{name:'Fault-injection evaluation', days:'Days 9-10', tier:'mvp'},
  5:{name:'Confirmed, deduplicated issues', days:'Days 11-13', tier:'stretch'},
  6:{name:'Benchmark and review UI', days:'Days 13-14', tier:'stretch'},
  7:{name:'Shippable capstone', days:'Days 15-16', tier:'ship'}
};
const AREAS = [
  ['backend','Backend','Collector, instrumentation, agent graph, actions, eval'],
  ['frontend','Frontend','Next.js trace viewer (MVP) and review dashboard (stretch)'],
  ['shared','Shared','Decisions, gate, manual baseline, README and demo']
];

// Features: one subagent each. owns = proposed paths only this feature may edit.
const FE = [
  {id:'dec', name:'Project decisions', tier:'mvp', owns:'The author, not an agent',
   summary:'The four open questions from the PRD. Answer these first; they unblock or shape other work.',
   done:'Each question has a written answer recorded in the PRD.'},
  {id:'con', name:'Contracts and fixtures', tier:'mvp', owns:'contracts/, fixtures/',
   summary:'Shared schemas, API and tool contracts, shared models and synthetic fixture data. Every other feature builds against these instead of waiting on another feature.',
   done:'Contracts and fixtures exist, and each parallel feature can run its tests with no other feature present.'},
  {id:'col', name:'Trace collector and API', tier:'mvp', owns:'services/collector/',
   summary:'Receives OpenTelemetry exports, stores and scores traces, and serves them through the trace API.',
   done:'A sample OTLP export is stored; both trace API endpoints return what the contract specifies; failed traces get scores.'},
  {id:'med', name:'Medas instrumentation and fault injection', tier:'mvp', owns:'The Medas repository (location TBD, outside TraceScan)',
   summary:'Emit the contracted spans from Medas, generate traffic, and switch on one of the six faults at a time.',
   done:'A Medas run emits the contracted spans; each fault can be turned on alone and visibly changes the traces.'},
  {id:'mcp', name:'Read-only MCP server', tier:'mvp', owns:'services/mcp_server/',
   summary:'The only way the agent reads traces. Read-only by database role, not by convention.',
   done:'Both tools return contracted output against seeded fixtures, and a write attempt fails.'},
  {id:'ui', name:'Trace viewer UI', tier:'mvp', owns:'ui/ (trace viewer routes and components)',
   summary:'Next.js pages to browse runs and inspect a trace, built against a mock of the trace API.',
   done:'List, filters, detail, span tree, span panel and badges work against the mock API.'},
  {id:'tri', name:'Triage analysis nodes', tier:'mvp', owns:'agent/analysis/',
   summary:'Collect, cluster, diagnose and draft nodes, developed against a stub MCP client that serves fixtures.',
   done:'Given fixture traces the nodes produce validated diagnoses and issue proposals with regression tests.'},
  {id:'rev', name:'Human review and dry-run actions', tier:'mvp', owns:'agent/review/, agent/actions/',
   summary:'Pause for approval, resume with decisions, and write approved items as local files.',
   done:'Given fixture proposals, nothing is written without approval and approved items appear as local files.'},
  {id:'met', name:'Eval ground truth and metrics', tier:'mvp', owns:'eval/metrics/',
   summary:'Fault-to-category ground truth and the metric calculators, tested on fixture results.',
   done:'Each metric returns the expected value on fixture results and the results table is written.'},
  {id:'int', name:'MVP integration and eval run', tier:'mvp', owns:'Lead agent; wiring and run scripts only',
   summary:'Joins the parts and runs the full fault-injection eval. Done by the lead after the parallel features land.',
   done:'Medas traces reach the viewer and the agent, and the eval has run on all six faults.'},
  {id:'gate', name:'Baseline, thresholds and MVP gate', tier:'mvp', owns:'The author, not an agent',
   summary:'Time a manual triage, set metric thresholds from the results, and decide what stretch work to cut.',
   done:'Thresholds are recorded in the PRD and a go or cut decision is made for stretch work.'},
  {id:'rep', name:'Replay reproduction', tier:'stretch', owns:'agent/reproduce/ and a sandbox endpoint in Medas',
   summary:'Replay a diagnosed failure against Medas and drop clusters that do not reproduce.',
   done:'Reproduced and unreproduced fixtures are told apart, and unreproduced ones never reach review.'},
  {id:'mem', name:'Known-issues memory', tier:'stretch', owns:'agent/memory/',
   summary:'Remember issues from earlier runs so a repeat failure updates an issue instead of duplicating it.',
   done:'A second run over the same traffic produces updates, not new issues.'},
  {id:'gh', name:'GitHub issues', tier:'stretch', owns:'agent/github/',
   summary:'Create and update real GitHub issues, only when dry run is off.',
   done:'With dry run off an approved proposal becomes an issue; with it on nothing is sent.'},
  {id:'dash', name:'Review dashboard', tier:'stretch', owns:'ui/review/, services/review_api/',
   summary:'Replace the terminal review with a web dashboard, built against a review API contract.',
   done:'A person can approve or reject each proposal in the browser and the run resumes.'},
  {id:'mast', name:'MAST-Data benchmark', tier:'stretch', owns:'eval/mast/',
   summary:'Compare the diagnoser with human labels on the published MAST-Data benchmark.',
   done:'An agreement figure between the diagnoser and the human labels is reported.'},
  {id:'sev', name:'Stretch evaluation rerun', tier:'stretch', owns:'eval/ (run scripts and results only)',
   summary:'Re-run the eval with replay and memory switched on and compare with the MVP run.',
   done:'A before and after comparison of duplicates and false positives is recorded.'},
  {id:'ship', name:'Deploy, README and demo', tier:'ship', owns:'deploy/, README.md',
   summary:'Package, deploy (or prepare a recorded run), document and record the three-minute demo.',
   done:'A viewer can follow the README, and the demo is recorded.'}
];

const T = [];
// add(feature, area, id, milestone, title, needs, note, kind)
const add = (feat, area, id, m, t, needs, n, kind) => T.push({feat, area, id, m, t, needs, n: n || null, kind: kind || 'task'});

// Decisions
add('dec','shared','d1',1,'Confirm building a custom tracing stack instead of using a platform such as Langfuse',[],'Open question in the PRD. Settle before tracing work starts.','decision');
add('dec','shared','d2',1,'Decide how sensitive clinical content in Medas traces is stored and shared',[],'Medas is clinician-facing. Affects storage and what may go into GitHub issues.','decision');
add('dec','shared','d4',6,'Decide whether the MAST-Data comparison joins the MVP',[],'Open question in the PRD: is fault injection enough on its own?','decision');
add('dec','shared','d3',7,'Confirm whether the course needs a deployed demo or a recorded one',[],null,'decision');

// Contracts and fixtures
add('con','backend','b1',1,'Create Postgres tables for traces and spans',['d1']);
add('con','backend','b2',1,'Create the scores table linked to traces',['b1']);
add('con','backend','b20',1,'Define the fixed failure taxonomy',[],'Category list is not defined in the source document.');
add('con','backend','b21',1,'Pydantic model for a diagnosis: category, cause, suggested fix, spans',['b20']);
add('con','backend','c7',1,'Define span attribute names for retrieval, model-call, tool-call and error spans',['b1'],'Medas writes these, the collector stores them, the agent reads them.');
add('con','backend','c1',1,'Write the trace API contract for list and detail (OpenAPI)',['b1','b2']);
add('con','backend','c2',1,'Write the MCP tool contract: tool names, inputs and outputs',['b1','b2']);
add('con','backend','c3',1,'Define shared models: graph state, proposal, review decision and run summary',['b21']);
add('con','backend','c4',1,'Create fixture traces: a few synthetic failed traces per fault, in the stored format',['b1','b2','b20'],'Lets every other feature work without the real collector or Medas.');
add('con','backend','c5',1,'Seed script: load the fixture traces into Postgres',['c4']);
add('con','backend','c6',2,'Create fixture proposals and review decisions for testing review and actions',['c3','c4']);
add('con','backend','b22',2,'Triage graph skeleton: shared state and a run entry point taking a time window',['c3']);

// Trace collector and API
add('col','backend','b3',1,'Collector: accept OpenTelemetry trace exports over HTTP',['b1']);
add('col','backend','b4',1,'Collector: store spans linked to their trace and parent span',['b3']);
add('col','backend','b5',1,'Collector: redact or drop sensitive fields before storing',['b4','d2'],'What to remove depends on the sensitive-data decision.');
add('col','backend','b11',1,'Scoring job: mark traces that contain errors or timeouts',['b4','b2']);
add('col','backend','b12',1,'Scoring job: mark low-quality answers',['b11'],'The scoring method is not defined in the source document.');
add('col','backend','b15',1,'Trace API: list traces with time-window and failed-only filters',['b4','c1']);
add('col','backend','b16',1,'Trace API: get one trace with all its spans',['b4','c1']);

// Medas instrumentation and fault injection
add('med','backend','b13',1,'Write a question set for Medas that exercises each injected fault',[]);
add('med','backend','b6',1,'Instrument Medas: one root span per request',['c7','d2']);
add('med','backend','b7',1,'Instrument Medas: retrieval spans with query and result count',['b6']);
add('med','backend','b8',1,'Instrument Medas: model-call spans with model, prompt size and token counts',['b6']);
add('med','backend','b9',1,'Instrument Medas: tool-call spans with name, arguments and errors',['b6']);
add('med','backend','b10',1,'Record upstream timeouts and errors on spans',['b8','b9']);
add('med','backend','b14',1,'Traffic generator: send the question set to Medas at a set rate',['b13','b6']);
add('med','backend','b41',4,'Fault selector: exactly one injected fault active per run',['b14']);
add('med','backend','b42',4,'Fault: empty retrieval',['b41','b7']);
add('med','backend','b43',4,'Fault: broken tool schema',['b41','b9']);
add('med','backend','b44',4,'Fault: truncated system prompt',['b41','b8']);
add('med','backend','b45',4,'Fault: small context window',['b41','b8']);
add('med','backend','b46',4,'Fault: weaker model',['b41','b8']);
add('med','backend','b47',4,'Fault: upstream timeouts',['b41','b10']);

// Read-only MCP server
add('mcp','backend','b17',2,'MCP server: skeleton using a read-only database role',['b1','c2']);
add('mcp','backend','b18',2,'MCP tool: list failed and low-score traces for a time window',['b17','c5']);
add('mcp','backend','b19',2,'MCP tool: get one trace with its spans',['b17','c5']);

// Trace viewer UI
add('ui','frontend','f1',1,'Create the Next.js app with page layout and navigation',[]);
add('ui','frontend','m1',1,'Mock trace API server that serves the fixtures, from the contract',['c1','c4']);
add('ui','frontend','f2',1,'Runs list page: table of traces with time, status and score',['f1','m1']);
add('ui','frontend','f3',1,'Runs list: time-window and failed-only filters',['f2']);
add('ui','frontend','f4',1,'Trace detail page: header with timing, status and score',['f1','m1']);
add('ui','frontend','f5',1,'Trace detail: span tree with nesting and durations',['f4']);
add('ui','frontend','f6',1,'Trace detail: span panel showing inputs, outputs and errors',['f5']);
add('ui','frontend','f7',1,'Failure and low-score badges on the list and the detail page',['f2','f4']);

// Triage analysis nodes
add('tri','backend','a1',2,'Stub MCP client that serves the fixture traces',['c2','c4']);
add('tri','backend','b23',2,'collect_traces node: fetch failed traces through the MCP client interface',['b22','a1']);
add('tri','backend','b24',2,'Turn each failed trace into text and an embedding',['b23']);
add('tri','backend','b25',2,'cluster_failures: HDBSCAN grouping, with noise kept apart',['b24']);
add('tri','backend','b26',2,'End the run cleanly when no clusters are found',['b25']);
add('tri','backend','b27',2,'diagnose_cluster: prompt and structured output for one cluster',['b21','b25']);
add('tri','backend','b28',2,'Run diagnose_cluster in parallel, one branch per cluster',['b27']);
add('tri','backend','b29',2,'Check that every span a diagnosis cites exists in its cluster',['b28']);
add('tri','backend','b30',2,'draft_proposals: issue title and body from a diagnosis',['b29']);
add('tri','backend','b31',2,'draft_proposals: regression test case from the failing input',['b30']);
add('tri','backend','b32',2,'Track token cost and wall-clock time for each run',['b22']);

// Human review and dry-run actions
add('rev','backend','b33',3,'Set up the Postgres checkpointer so a run can wait',['b22']);
add('rev','backend','b34',3,'human_review: pause the run with its proposals',['b33','c6']);
add('rev','backend','b35',3,'Terminal review: show proposals and collect approve or reject for each',['b34'],'The review UI is stretch in the source, so the MVP reviews in the terminal.');
add('rev','backend','b36',3,'Resume the run with decisions; end it if nothing is approved',['b35']);
add('rev','backend','b37',3,'apply_actions: process approved proposals only',['b36']);
add('rev','backend','b38',3,'Add the dry-run flag, on by default',['b37']);
add('rev','backend','b39',3,'Dry run: write each approved issue to a local file',['b38']);
add('rev','backend','b40',3,'Dry run: write each approved regression case to a local eval dataset file',['b38']);

// Eval ground truth and metrics
add('met','backend','b48',4,'Ground-truth file: each fault with its expected category',['b20']);
add('met','backend','b50',4,'Metric: detection rate',['b48','c3','c4']);
add('met','backend','b51',4,'Metric: root-cause accuracy',['b50']);
add('met','backend','b52',4,'Metric: false positives',['b50']);
add('met','backend','b53',4,'Metric: duplicate issues on a second run',['c3','c4']);
add('met','backend','b54',4,'Metric: cost and time per run',['c3','c4']);
add('met','backend','b55',4,'Write the eval results table to a file',['b51','b52','b53','b54']);

// MVP integration and eval run
add('int','backend','i1',1,'Send Medas spans to the real collector and confirm they are stored',['b10','b4']);
add('int','frontend','i2',1,'Point the trace viewer at the real trace API',['f7','b15','b16','i1']);
add('int','backend','i4',3,'Wire the analysis and review nodes into one graph and run it on fixtures',['b31','b40']);
add('int','backend','i3',3,'Run the full graph against the real MCP server and real Medas traces',['i4','b18','b19','i1']);
add('int','backend','b49',4,'Eval runner: for each fault, generate traffic and run TraceScan',['b14','b42','b43','b44','b45','b46','b47','b32','i3']);
add('int','backend','e1',4,'Run the full eval and save the results table',['b49','b55']);

// Baseline, thresholds and gate
add('gate','shared','s1',4,'Time one manual triage of a faulty run as the baseline',['b41','b14'],'Gives the PRD its missing evidence that the problem is real.');
add('gate','shared','s2',4,'Set success thresholds for each metric from the results',['e1','s1']);
add('gate','shared','g1',4,'MVP gate, day 10: review results and cut stretch work if behind',['s2'],null,'gate');

// Replay reproduction (stretch)
add('rep','backend','b56',5,'Sandbox endpoint in Medas: run it on given inputs',['g1']);
add('rep','backend','b57',5,'Extract the replay inputs from a cluster\'s traces',['g1','c4']);
add('rep','backend','b58',5,'reproduce_failure node: replay each diagnosis in parallel',['b57','b56','b28']);
add('rep','backend','b59',5,'Rule for what counts as reproduced, per failure category',['b58','b20'],'Not defined in the source document.');
add('rep','backend','b60',5,'draft_proposals: drop clusters that did not reproduce',['b59','b30']);

// Known-issues memory (stretch)
add('mem','backend','b61',5,'Create the known-issues table',['g1','b1']);
add('mem','backend','b62',5,'Save each applied proposal to the known-issues table',['b61','b39']);
add('mem','backend','b63',5,'match_known_issues: compare a cluster with stored issues',['b61','b25']);
add('mem','backend','b64',5,'draft_proposals: update-existing-issue proposal type',['b63','b30']);
add('mem','backend','b65',5,'apply_actions: update an existing issue instead of creating one',['b64','b62']);

// GitHub issues (stretch)
add('gh','backend','b66',5,'GitHub client: create an issue',['g1','b37','d2']);
add('gh','backend','b67',5,'GitHub client: update an existing issue',['b66','b64']);
add('gh','backend','b68',5,'Send GitHub writes only when dry run is off',['b66','b38']);

// Review dashboard (stretch)
add('dash','backend','c8',6,'Write the review API contract',['b34','g1']);
add('dash','backend','b75',6,'Review API: list runs waiting for review with their proposals',['c8']);
add('dash','backend','b76',6,'Review API: submit decisions and resume the run',['c8','b75','b36']);
add('dash','frontend','f8',6,'Review page: runs waiting for review, built against a mock of the review API',['f1','c8']);
add('dash','frontend','f9',6,'Proposal card: issue title, body and regression test',['f8']);
add('dash','frontend','f10',6,'Evidence panel: cluster traces linking to the trace viewer',['f9','f5']);
add('dash','frontend','f11',6,'Show whether the failure reproduced, when that data is present',['f9']);
add('dash','frontend','f12',6,'Approve and reject controls on each proposal',['f9']);
add('dash','frontend','f13',6,'Submit decisions and resume the run',['f12']);
add('dash','frontend','f14',6,'Show the result after apply: dry-run file or GitHub issue link',['f13']);
add('dash','frontend','i5',6,'Connect the review dashboard to the real review API',['f14','b76']);

// MAST-Data benchmark (stretch)
add('mast','backend','b71',6,'Load the MAST-Data benchmark traces',['d4']);
add('mast','backend','b72',6,'Map MAST-Data failure labels onto the taxonomy',['b71','b20']);
add('mast','backend','b73',6,'Run the diagnoser over the MAST-Data traces',['b72','b28']);
add('mast','backend','b74',6,'Report agreement between the diagnoser and human labels',['b73']);

// Stretch evaluation rerun
add('sev','backend','b69',5,'Re-run the eval with replay and memory switched on',['b60','b65','e1']);
add('sev','backend','b70',5,'Compare duplicate and false-positive rates with the MVP run',['b69']);

// Ship
add('ship','backend','b77',7,'Package the collector, database and MCP server to run together',['g1']);
add('ship','backend','b78',7,'Deploy the backend services',['b77','d3'],'Skip if the demo is recorded.');
add('ship','frontend','f15',7,'Deploy the trace viewer',['f7','b78','d3'],'Skip if the demo is recorded.');
add('ship','shared','s3',7,'Write the README',['g1']);
add('ship','shared','s4',7,'Record the three-minute demo',['s3','d3']);

// ---- validation and derived data ----
const byId = {};
T.forEach(x => { if (byId[x.id]) throw new Error('duplicate id ' + x.id); byId[x.id] = x; });
const FBY = Object.fromEntries(FE.map(f => [f.id, f]));
// merge per-card description, details and done-when; every card needs one and no entry may be orphaned
const DET = require('./card-details.js');
Object.keys(DET).forEach(id => { if (!byId[id]) throw new Error('details for unknown card ' + id); });
T.forEach(x => {
  const d = DET[x.id];
  if (!d) throw new Error('no details for card ' + x.id);
  if (!d.d || !d.how || !d.how.length || !d.ok) throw new Error('incomplete details for card ' + x.id);
  x.d = d.d; x.how = d.how; x.ok = d.ok;
});
T.forEach(x => {
  if (!FBY[x.feat]) throw new Error('unknown feature ' + x.feat + ' on ' + x.id);
  x.needs.forEach(n => { if (!byId[n]) throw new Error(x.id + ' needs missing ' + n); });
});
const mark = {};
function visitCard(id, stack){
  if (mark[id] === 2) return;
  if (mark[id] === 1) throw new Error('card cycle at ' + stack.concat(id).join(' > '));
  mark[id] = 1; byId[id].needs.forEach(n => visitCard(n, stack.concat(id))); mark[id] = 2;
}
T.forEach(x => visitCard(x.id, []));

const ext = {};
T.forEach(x => x.needs.forEach(n => {
  const df = byId[n].feat;
  if (df !== x.feat) { ((ext[x.feat] ??= {})[df] ??= new Set()).add(n); }
}));
const waveMemo = {};
function wave(fid, stack){
  if (fid === 'dec') return 0;
  if (waveMemo[fid] != null) return waveMemo[fid];
  if (stack.includes(fid)) throw new Error('feature cycle ' + stack.concat(fid).join(' > '));
  const deps = Object.keys(ext[fid] || {}).filter(d => d !== 'dec');
  return waveMemo[fid] = 1 + Math.max(0, ...deps.map(d => wave(d, stack.concat(fid))));
}
const FE2 = FE.map(f => ({
  ...f,
  wave: wave(f.id, []),
  needs: Object.entries(ext[f.id] || {}).map(([feat, set]) => ({feat, cards: [...set]}))
}));

// independence check: MVP wave-2 features may only lean on contracts and decisions
const violations = [];
FE2.filter(f => f.wave === 2 && f.tier === 'mvp').forEach(f =>
  f.needs.forEach(n => { if (!['con', 'dec'].includes(n.feat)) violations.push(f.id + ' needs ' + n.feat + ' (' + n.cards.join(',') + ')'); }));

// ---- write the board data block ----
let html = fs.readFileSync(HTML, 'utf8');
const s = html.indexOf('const MS = ');
const km = html.match(/const KEY = 'tracescan-board-v\d+';/);
if (s < 0 || !km) throw new Error('markers not found in html');
const e = html.indexOf(km[0]);
const data =
  'const MS = ' + JSON.stringify(MS) + ';\n' +
  'const AREAS = ' + JSON.stringify(AREAS) + ';\n' +
  'const FEATURES = ' + JSON.stringify(FE2) + ';\n' +
  'const FBY = Object.fromEntries(FEATURES.map(f => [f.id, f]));\n' +
  'const T = ' + JSON.stringify(T) + ';\n\n';
html = html.slice(0, s) + data + "const KEY = 'tracescan-board-v3';" + html.slice(e + km[0].length);
fs.writeFileSync(HTML, html);

// ---- write the work-packages brief ----
const tierName = {mvp: 'MVP', stretch: 'Stretch', ship: 'Ship'};
const waves = {};
FE2.forEach(f => (waves[f.wave] ??= []).push(f));
let md = '';
md += '# TraceScan work packages\n\n';
md += '> Derived from `tracescan.prd.md` and the architecture overview. Split into features that independent subagents can build in parallel. Paths are proposed, not decided. The Medas repository location is TBD.\n\n';
md += '## How parallel work stays independent\n\n';
md += '1. **Contracts first.** The Contracts and fixtures feature produces the API, tool and model contracts plus synthetic fixture traces. Every parallel feature builds and tests against those, never against another feature\'s code.\n';
md += '2. **One owner per path.** A feature edits only the paths it owns. Anything else goes through the lead.\n';
md += '3. **Stubs and mocks stand in for neighbours.** Examples: `m1` mocks the trace API, `a1` stubs the MCP client, `c5` seeds Postgres with fixtures.\n';
md += '4. **Contracts do not change inside a feature.** If a contract is wrong, report it; the lead changes it and tells the affected features.\n';
md += '5. **Joins are separate cards.** The MVP integration feature connects real parts after the parallel work lands.\n\n';
md += '### Standard brief for each subagent\n\n';
md += '> You own the feature **{name}** in `tracescan.work-packages.md`. Read `contracts/` and `fixtures/` first. Build only the cards listed for your feature, in dependency order. Edit only the paths you own. Use the stubs and mocks named in the cards instead of other features\' code. Your tests must pass with fixtures alone. Finish by reporting the files you changed, which cards are done, and any contract problem you found. Do not change contracts yourself.\n\n';
md += '## Waves\n\n';
md += 'A wave can start when the features in earlier waves have landed (decisions excluded). Features in the same wave can run at the same time.\n\n';
md += '| Wave | Features | Parallel agents |\n|---|---|---|\n';
Object.keys(waves).sort((a, b) => a - b).forEach(w => {
  const list = waves[w];
  md += '| ' + (w === '0' ? 'Decide first' : w) + ' | ' + list.map(f => f.name + (f.tier !== 'mvp' ? ' (' + tierName[f.tier].toLowerCase() + ')' : '')).join('; ') + ' | ' + (w === '0' ? '0 (author)' : list.filter(f => !['int', 'gate'].includes(f.id)).length) + ' |\n';
});
md += '\n`*` after a card id below marks a dependency on another feature.\n\n';
md += '## Features\n\n';
FE2.forEach(f => {
  const cards = T.filter(x => x.feat === f.id);
  md += '### ' + f.name + '\n\n';
  md += '- **Wave:** ' + (f.wave === 0 ? 'decide first' : f.wave) + ' · **Tier:** ' + tierName[f.tier] + '\n';
  md += '- **Owns:** ' + f.owns + '\n';
  md += '- **Goal:** ' + f.summary + '\n';
  md += '- **Builds against:** ' + (f.needs.length ? f.needs.map(n => FBY[n.feat].name + ' (' + n.cards.join(', ') + ')').join('; ') : 'nothing outside this feature') + '\n';
  md += '- **Done when:** ' + f.done + '\n\n';
  md += '| Card | Area | Task | Needs |\n|---|---|---|---|\n';
  cards.forEach(x => {
    const needs = x.needs.map(n => n + (byId[n].feat !== f.id ? '*' : '')).join(', ') || '—';
    md += '| ' + x.id + ' | ' + x.area + ' | ' + x.t + (x.n ? ' (' + x.n + ')' : '') + ' | ' + needs + ' |\n';
  });
  md += '\n';
  md += '#### Card details: ' + f.name + '\n\n';
  cards.forEach(x => {
    md += '**' + x.id + '. ' + x.t + '**\n\n';
    md += x.d + '\n\n';
    x.how.forEach(h => { md += '- ' + h + '\n'; });
    md += '- **Done when:** ' + x.ok + '\n';
    if (x.n) md += '- **Open point:** ' + x.n + '\n';
    md += '\n';
  });
});
fs.writeFileSync(MD, md);

// ---- report ----
const cnt = {}; T.forEach(x => cnt[x.area] = (cnt[x.area] || 0) + 1);
console.log('cards', T.length, cnt, 'features', FE.length);
console.log('independence violations (MVP wave 2):', violations.length ? violations : 'none');
Object.keys(waves).sort((a, b) => a - b).forEach(w => console.log('wave', w + ':', waves[w].map(f => f.id).join(', ')));
console.log('wave-2 externals:');
FE2.filter(f => f.wave === 2 && f.tier === 'mvp').forEach(f => console.log(' ', f.id, '<-', f.needs.map(n => n.feat + '[' + n.cards.join(',') + ']').join(' ') || 'none'));
console.log('ready at start:', T.filter(x => !x.needs.length).map(x => x.id).join(', '));
