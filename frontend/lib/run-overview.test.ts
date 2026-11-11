import assert from "node:assert/strict";
import { test } from "node:test";
import {
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
  failed_traces: 4,
  clusters: 2,
  unclustered: 1,
  diagnoses: 1,
  diagnosis_failures: 1,
  proposals: 2,
  actions_log: [],
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

test("a paused run waits at the review, with the unbuilt stages shown as such", () => {
  assert.deepEqual(states(read(PAUSED)), {
    collect: "done",
    cluster: "done",
    diagnose: "done",
    reproduce: "not_built",
    match: "not_built",
    draft: "done",
    review: "waiting",
    apply: "pending",
  });
  const [, cluster, diagnose] = pipeline(read(PAUSED));
  assert.equal(cluster.detail, "2 clusters · 1 isolated");
  assert.equal(diagnose.detail, "1 diagnosed · 1 failed");
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
  assert.ok(stages.every((s) => s.state === "done" || s.state === "not_built"));
  assert.equal(
    stages.find((s) => s.key === "review")?.detail,
    "1 approved · 1 rejected",
  );
  assert.equal(stages.find((s) => s.key === "apply")?.detail, "1 action");
});

test("a run that found nothing skips everything after the collection", () => {
  const empty = {
    ...SUMMARY,
    failed_traces: 0,
    clusters: 0,
    unclustered: 0,
    diagnoses: 0,
    diagnosis_failures: 0,
    proposals: 0,
  };
  const s = states(
    read({
      status: "completed",
      summary: empty,
      clusters: [],
    }),
  );
  assert.equal(s.collect, "done");
  assert.equal(s.cluster, "skipped");
  assert.equal(s.apply, "skipped");
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
