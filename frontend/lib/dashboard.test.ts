import assert from "node:assert/strict";
import { test } from "node:test";
import {
  categoryBreakdown,
  failureRate,
  failureTrend,
  largestClusters,
  latestAnalyzed,
  oldestWaiting,
  outcomes,
  runStats,
} from "./dashboard.ts";
import { formatAge } from "./format.ts";
import type { ClusterDetail } from "./run-overview.ts";
import { emptyOverview } from "./run-overview.ts";
import type { RunRecord } from "./types.ts";

const run = (id: string, over: Partial<RunRecord> = {}): RunRecord => ({
  run_id: id,
  target_app: "medas",
  since: null,
  until: null,
  status: "completed",
  started_by: "local",
  created_at: "2026-11-11T10:00:00Z",
  ended_at: "2026-11-11T10:01:00Z",
  failed_traces: 4,
  clusters: 2,
  proposals: 2,
  ...over,
});

const cluster = (
  id: string,
  traces: number,
  category: string | null,
): ClusterDetail => ({
  cluster_id: id,
  signature: `sig ${id}`,
  method: "hdbscan",
  trace_ids: Array.from({ length: traces }, (_, i) => `${id}-${i}`),
  exemplar_trace_ids: [`${id}-0`],
  diagnosis:
    category === null
      ? null
      : {
          category,
          root_cause: "",
          suggested_fix: "",
          confidence: 0.8,
          evidence: [],
          evidence_check: "valid",
        },
  diagnosis_failed: category === null,
  usage: { calls: 1, tokens: 1, cost_usd: 0 },
  verification: "unverified",
  decision: null,
});

const NOW = new Date("2026-11-11T12:00:00Z").getTime();

test("the latest analyzed run is the newest that found clusters", () => {
  const runs = [
    run("a", { status: "in_progress", clusters: 0 }),
    run("b", { status: "completed", clusters: 0, failed_traces: 0 }),
    run("c", { status: "review_required" }),
    run("d"),
  ];
  assert.equal(latestAnalyzed(runs)?.run_id, "c");
  assert.equal(latestAnalyzed([runs[0]]), null);
});

test("the failure rate is failed of judged, and null with nothing judged", () => {
  const o = emptyOverview("r");
  assert.equal(failureRate(o), null);
  assert.equal(
    failureRate({
      ...o,
      summary: { ...o.summary, traces: 8, failed_traces: 2 },
    }),
    0.25,
  );
});

test("categories are weighted by traces, undiagnosed ones kept", () => {
  const shares = categoryBreakdown([
    cluster("c0", 3, "infra_error"),
    cluster("c1", 5, "context_overflow"),
    cluster("c2", 2, "infra_error"),
    cluster("c3", 1, null),
  ]);
  assert.deepEqual(shares, [
    { category: "context_overflow", traces: 5, clusters: 1 },
    { category: "infra_error", traces: 5, clusters: 2 },
    { category: "undiagnosed", traces: 1, clusters: 1 },
  ]);
});

test("the largest clusters come first", () => {
  const ids = largestClusters(
    [cluster("a", 1, "x"), cluster("b", 9, "x"), cluster("c", 4, "x")],
    2,
  ).map((c) => c.cluster_id);
  assert.deepEqual(ids, ["b", "c"]);
});

test("the trend keeps the newest finished runs, oldest first", () => {
  const runs = [
    run("new", { status: "review_required" }),
    run("bad", { status: "failed" }),
    run("mid"),
    run("old"),
  ];
  assert.deepEqual(
    failureTrend(runs, 2).map((r) => r.run_id),
    ["mid", "new"],
  );
});

test("outcomes count the last 7 days by status", () => {
  const counts = outcomes(
    [
      run("a"),
      run("b", { status: "failed" }),
      run("c", { created_at: "2026-10-01T00:00:00Z" }),
    ],
    NOW,
  );
  assert.equal(counts.completed, 1);
  assert.equal(counts.failed, 1);
});

test("the oldest wait counts from when the run stopped", () => {
  assert.equal(oldestWaiting([run("a")], NOW), null);
  const wait = oldestWaiting(
    [
      run("a", { status: "review_required", ended_at: "2026-11-11T11:00:00Z" }),
      run("b", { status: "review_required", ended_at: null }),
    ],
    NOW,
  );
  assert.equal(wait, 2 * 3_600_000);
  assert.equal(formatAge(wait as number), "2 h");
  assert.equal(formatAge(5 * 60_000), "5 min");
  assert.equal(formatAge(3 * 86_400_000), "3 d");
});

const RUN_W = run("w", {
  status: "review_required",
  failed_traces: 12,
  proposals: 3,
});

test("the overview counts the last 7 days and what waits for a review", () => {
  const now = new Date("2026-11-11T12:00:00Z").getTime();
  const old = run("old", { created_at: "2026-10-01T00:00:00Z" });
  const done = run("done", { failed_traces: 3 });
  assert.deepEqual(runStats([RUN_W, done, old], now), {
    runs: 2,
    failures: 15,
    awaiting: 1,
    openProposals: 3,
  });
});
