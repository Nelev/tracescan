import assert from "node:assert/strict";
import { test } from "node:test";
import {
  foldProgress,
  type LiveProgress,
  NO_PROGRESS,
  type ProgressData,
} from "./progress.ts";
import {
  emptyOverview,
  formatUsage,
  parseRunOverview,
  pipeline,
  type RunOverview,
  totalUsage,
} from "./run-overview.ts";

const CLUSTER = {
  cluster_id: "c0",
  signature: "execute_tool export_conversation ValidationError",
  method: "hdbscan",
  trace_ids: ["t1", "t2", "t3"],
  exemplar_trace_ids: ["t1", "t2"],
  diagnosis: {
    category: "tool_schema_error",
    root_cause: "The tool's format argument is not a string.",
    suggested_fix: "Send the format as a string.",
    confidence: 0.8,
    evidence: [{ trace_id: "t1", span_id: "s1", note: "validation error" }],
    evidence_check: "valid",
  },
  diagnosis_failed: false,
  usage: { calls: 1, tokens: 1200, cost_usd: 0.004 },
  verification: "unverified",
  decision: null,
};

const ISOLATED = {
  ...CLUSTER,
  cluster_id: "c1",
  method: "isolated",
  trace_ids: ["t9"],
  exemplar_trace_ids: ["t9"],
  diagnosis: null,
  diagnosis_failed: true,
  usage: { calls: 2, tokens: 0, cost_usd: 0 },
};

const SUMMARY = {
  run_id: "r1",
  traces: 10,
  judged: 9,
  judge_failures: 1,
  failed_traces: 4,
  clusters: 2,
  unclustered: 1,
  diagnoses: 1,
  diagnosis_failures: 1,
  proposals: 2,
  actions_log: [],
};

/** A run that found no failures: everything after the judge is zero. */
const NOTHING_FAILED = {
  ...SUMMARY,
  judged: 10,
  judge_failures: 0,
  failed_traces: 0,
  clusters: 0,
  unclustered: 0,
  diagnoses: 0,
  diagnosis_failures: 0,
  proposals: 0,
};

const PAUSED = {
  status: "review_required",
  summary: SUMMARY,
  clusters: [CLUSTER, ISOLATED],
};

const read = (body: unknown): RunOverview => {
  const overview = parseRunOverview(body);
  assert.ok(overview);
  return overview;
};

const states = (o: RunOverview) =>
  Object.fromEntries(pipeline(o).map((s) => [s.key, s.state]));

test("a run on contract is read whole", () => {
  const o = read(PAUSED);
  assert.equal(o.clusters.length, 2);
  assert.equal(o.clusters[0].diagnosis?.evidence[0].span_id, "s1");
  assert.equal(o.clusters[1].diagnosis, null);
});

test("one cluster off contract makes the whole run unreadable", () => {
  assert.equal(
    parseRunOverview({
      ...PAUSED,
      clusters: [{ ...CLUSTER, method: "magic" }],
    }),
    null,
  );
  assert.equal(
    parseRunOverview({
      ...PAUSED,
      clusters: [
        { ...CLUSTER, diagnosis: { ...CLUSTER.diagnosis, evidence: [{}] } },
      ],
    }),
    null,
  );
  assert.equal(parseRunOverview({ ...PAUSED, status: "paused" }), null);
  assert.equal(parseRunOverview(null), null);
});

test("a paused run waits at the review", () => {
  assert.deepEqual(states(read(PAUSED)), {
    collect: "done",
    judge: "done",
    cluster: "done",
    diagnose: "done",
    draft: "done",
    review: "waiting",
    apply: "pending",
  });
  const [collect, judge, cluster, diagnose] = pipeline(read(PAUSED));
  assert.equal(collect.detail, "10 traces");
  assert.equal(judge.detail, "4 failed of 9 · 1 not judged");
  assert.equal(cluster.detail, "2 clusters · 1 isolated");
  assert.equal(diagnose.detail, "1 of 2 · 1 failed");
  assert.ok(pipeline(read(PAUSED)).every((st) => st.progress === null));
});

test("a reviewed run is done end to end, with the decisions counted", () => {
  const o = read({
    ...PAUSED,
    status: "completed",
    summary: { ...SUMMARY, actions_log: ["wrote issues/c0.md"] },
    clusters: [
      { ...CLUSTER, decision: "approve" },
      { ...ISOLATED, decision: "reject" },
    ],
  });
  const stages = pipeline(o);
  assert.ok(stages.every((s) => s.state === "done"));
  assert.equal(
    stages.find((s) => s.key === "review")?.detail,
    "1 approved · 1 rejected",
  );
  assert.equal(stages.find((s) => s.key === "apply")?.detail, "1 action");
});

test("a run that found nothing skips everything after the collection", () => {
  const s = states(
    read({ status: "completed", summary: NOTHING_FAILED, clusters: [] }),
  );
  assert.equal(s.collect, "done");
  assert.equal(s.cluster, "skipped");
  assert.equal(s.apply, "skipped");
});

test("an empty window is collected and has nothing to judge", () => {
  const none = { ...NOTHING_FAILED, traces: 0, judged: 0 };
  const s = states(read({ status: "completed", summary: none, clusters: [] }));
  assert.equal(s.collect, "done");
  assert.equal(s.judge, "skipped");
  assert.equal(s.cluster, "skipped");
});

test("a run whose traces are being judged is running at the judge", () => {
  const o = read({
    status: "in_progress",
    summary: { ...NOTHING_FAILED, judged: 0 },
    clusters: [],
  });
  const s = states(o);
  assert.equal(s.collect, "done");
  assert.equal(s.judge, "running");
  assert.equal(s.cluster, "pending");
  assert.equal(pipeline(o).find((st) => st.key === "judge")?.detail, "—");
});

test("a failed or aborted run marks the stage it stopped at", () => {
  const early = {
    ...SUMMARY,
    clusters: 0,
    diagnoses: 0,
    diagnosis_failures: 0,
    proposals: 0,
  };
  const failed = states(
    read({ status: "failed", summary: early, clusters: [] }),
  );
  assert.equal(failed.collect, "done");
  assert.equal(failed.judge, "done");
  assert.equal(failed.cluster, "failed");
  assert.equal(failed.diagnose, "pending");
  const aborted = states(
    read({ status: "aborted", summary: early, clusters: [] }),
  );
  assert.equal(aborted.cluster, "stopped");
});

test("the spend adds up over the clusters and reads short", () => {
  const total = totalUsage(read(PAUSED).clusters);
  assert.deepEqual(total, { calls: 3, tokens: 1200, cost_usd: 0.004 });
  assert.equal(formatUsage(total), "3 calls · 1,200 tokens · $0.004");
});

const live = (events: ProgressData[]): LiveProgress =>
  events.reduce(foldProgress, NO_PROGRESS);
const ev = (
  event: ProgressData["event"],
  node: string,
  extra: Partial<ProgressData> = {},
): ProgressData => ({
  event,
  node,
  clusterId: null,
  ok: true,
  counts: {},
  ...extra,
});

test("while streaming, the judge runs with its share done", () => {
  const progress = live([
    ev("node_started", "collect_traces"),
    ev("node_finished", "collect_traces", { counts: { traces: 48 } }),
    ev("node_progress", "score_trace", { counts: { done: 12, total: 48 } }),
  ]);
  const stages = pipeline(emptyOverview("r1"), progress);
  const [collect, judge, cluster] = stages;
  assert.equal(collect.state, "done");
  assert.equal(collect.detail, "48 traces");
  assert.equal(judge.state, "running");
  assert.equal(judge.progress, 0.25);
  assert.equal(judge.detail, "12 of 48 judged");
  assert.equal(cluster.state, "pending");
});

test("while streaming, the diagnoses count up and the run waits at the review", () => {
  const diagnosing = live([
    ev("node_finished", "collect_traces", { counts: { traces: 48 } }),
    ev("node_finished", "join_scores", { counts: { failed_traces: 22 } }),
    ev("node_finished", "cluster_failures", { counts: { clusters: 4 } }),
    ev("node_started", "diagnose_cluster", { clusterId: "c0" }),
    ev("node_finished", "diagnose_cluster", { clusterId: "c0" }),
  ]);
  const stages = pipeline(emptyOverview("r1"), diagnosing);
  const diagnose = stages.find((s) => s.key === "diagnose");
  assert.equal(diagnose?.state, "running");
  assert.equal(diagnose?.progress, 0.25);
  assert.equal(diagnose?.detail, "1 of 4");
  assert.equal(stages.find((s) => s.key === "judge")?.detail, "22 failed");

  const paused = live([
    ev("node_finished", "draft_proposals", { counts: { proposals: 4 } }),
    ev("node_started", "human_review"),
    ev("node_paused", "human_review"),
  ]);
  const at = Object.fromEntries(
    pipeline(emptyOverview("r1"), paused).map((s) => [s.key, s.state]),
  );
  assert.equal(at.diagnose, "done");
  assert.equal(at.review, "waiting");
  assert.equal(at.apply, "pending");
});

test("a node that failed marks its stage", () => {
  const failed = live([
    ev("node_finished", "collect_traces", { counts: { traces: 3 } }),
    ev("node_failed", "cluster_failures"),
  ]);
  const at = Object.fromEntries(
    pipeline(emptyOverview("r1"), failed).map((s) => [s.key, s.state]),
  );
  assert.equal(at.cluster, "failed");
});

test("the cluster map is read with the run, and missing reads as none", () => {
  const map = {
    projection: "pca",
    trust: 0.9,
    points: [
      {
        trace_ids: ["t1", "t2", "t3"],
        x: 0.1,
        y: -0.2,
        z: 1,
        cluster_id: "c0",
        stage: "hdbscan",
        hdbscan_label: 0,
        membership: 0.8,
      },
    ],
  };
  assert.deepEqual(read({ ...PAUSED, cluster_map: map }).cluster_map, map);
  assert.equal(read({ ...PAUSED, cluster_map: null }).cluster_map, null);
  assert.equal(read(PAUSED).cluster_map, null); // a backend from before the map
  assert.equal(
    parseRunOverview({
      ...PAUSED,
      cluster_map: { ...map, projection: "umap" },
    }),
    null,
  );
});
