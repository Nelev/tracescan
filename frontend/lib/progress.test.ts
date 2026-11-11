import assert from "node:assert/strict";
import { test } from "node:test";
import {
  diagnosesIn,
  foldProgress,
  NO_PROGRESS,
  type ProgressData,
  parseProgress,
} from "./progress.ts";

const read = (data: unknown): ProgressData => {
  const parsed = parseProgress(data);
  assert.ok(parsed);
  return parsed;
};

test("an event off contract is not read", () => {
  assert.equal(parseProgress({ event: "node_started" }), null);
  assert.equal(parseProgress({ event: "boom", node: "a" }), null);
  assert.equal(parseProgress([1]), null);
});

test("nodes, counts and checkpoints follow the events", () => {
  const live = [
    { event: "node_started", node: "collect_traces" },
    { event: "node_finished", node: "collect_traces", counts: { traces: 9 } },
  ]
    .map(read)
    .reduce(foldProgress, NO_PROGRESS);
  assert.deepEqual(live.nodes, { collect_traces: "done" });
  assert.deepEqual(live.counts, { traces: 9 });
  assert.equal(live.checkpoints, 1);
});

test("the judge's share is kept from its progress events", () => {
  const live = foldProgress(
    NO_PROGRESS,
    read({
      event: "node_progress",
      node: "score_trace",
      counts: { done: 3, total: 12 },
    }),
  );
  assert.deepEqual(live.judge, { done: 3, total: 12 });
  assert.equal(live.checkpoints, 0);
});

test("diagnose branches are tracked per cluster and load no checkpoint", () => {
  const live = [
    { event: "node_started", node: "diagnose_cluster", cluster_id: "c0" },
    { event: "node_started", node: "diagnose_cluster", cluster_id: "c1" },
    { event: "node_started", node: "diagnose_cluster", cluster_id: "c2" },
    { event: "node_finished", node: "diagnose_cluster", cluster_id: "c0" },
    {
      event: "node_finished",
      node: "diagnose_cluster",
      cluster_id: "c1",
      ok: false,
    },
  ]
    .map(read)
    .reduce(foldProgress, NO_PROGRESS);
  assert.deepEqual(live.diagnoses, { c0: "done", c1: "failed", c2: "running" });
  assert.equal(diagnosesIn(live, "done"), 1);
  assert.equal(live.checkpoints, 0);
});

test("folding never changes the progress it was given", () => {
  const before = structuredClone(NO_PROGRESS);
  foldProgress(NO_PROGRESS, read({ event: "node_finished", node: "x" }));
  assert.deepEqual(NO_PROGRESS, before);
});
