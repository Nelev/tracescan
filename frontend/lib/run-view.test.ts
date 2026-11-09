import assert from "node:assert/strict";
import { test } from "node:test";
import type { ProgressEvent, RunEvent } from "./events.ts";
import {
  describeProgress,
  foldEvent,
  freezeView,
  INITIAL_VIEW,
  type RunView,
  totals,
} from "./run-view.ts";

// The fold never reads task_id, so every event carries the same one.
const progress = (p: Omit<ProgressEvent, "task_id">): RunEvent => ({
  kind: "progress",
  progress: { task_id: "t", ...p },
});
const started = (node: string, cluster_id?: string) =>
  progress({ event: "node_started", node, cluster_id });
const finished = (
  node: string,
  counts?: Record<string, number>,
  extra: Partial<ProgressEvent> = {},
) => progress({ event: "node_finished", node, counts, ...extra });

function run(events: RunEvent[], view: RunView = INITIAL_VIEW): RunView {
  return events.reduce((v, e, i) => foldEvent(v, e, (i + 1) * 100), view);
}

function must<T>(found: T | undefined, what: string): T {
  assert.ok(found, what);
  return found;
}
const stage = (view: RunView, node: string) =>
  must(
    view.stages.find((s) => s.node === node),
    `stage ${node}`,
  );
const cluster = (view: RunView, id: string) =>
  must(
    view.clusters.find((c) => c.clusterId === id),
    `cluster ${id}`,
  );

test("starts with every known stage pending and no clusters", () => {
  assert.equal(INITIAL_VIEW.clusters.length, 0);
  assert.ok(INITIAL_VIEW.stages.every((s) => s.status === "pending"));
  assert.equal(INITIAL_VIEW.stages[0].node, "collect_traces");
});

test("a happy path walks the stages and counts clusters", () => {
  const view = run([
    started("collect_traces"),
    finished("collect_traces", { failed_traces: 12 }),
    started("cluster_failures"),
    finished("cluster_failures", { clusters: 2, unclustered: 1 }),
    started("diagnose_cluster", "c-1"),
    started("diagnose_cluster", "c-2"),
    finished("diagnose_cluster", { diagnoses: 1 }, { cluster_id: "c-1" }),
  ]);

  assert.equal(stage(view, "collect_traces").status, "done");
  assert.equal(stage(view, "cluster_failures").status, "done");
  // One branch is still out, so the fan-out stage is running.
  assert.equal(stage(view, "diagnose_cluster").status, "running");
  assert.equal(stage(view, "diagnose_cluster").active, 1);
  assert.equal(cluster(view, "c-1").status, "done");
  assert.equal(cluster(view, "c-2").status, "running");
  assert.deepEqual(totals(view), {
    failedTraces: 12,
    clusters: 2,
    unclustered: 1,
    settled: 1,
    failed: 0,
  });
  assert.equal(describeProgress(view), "1 of 2 clusters diagnosed");
});

test("fan-out counts are summed over its tasks", () => {
  const view = run([
    started("diagnose_cluster", "c-1"),
    started("diagnose_cluster", "c-2"),
    finished("diagnose_cluster", { diagnoses: 1 }, { cluster_id: "c-1" }),
    finished("diagnose_cluster", { diagnoses: 1 }, { cluster_id: "c-2" }),
  ]);
  assert.equal(stage(view, "diagnose_cluster").counts.diagnoses, 2);
  assert.equal(stage(view, "diagnose_cluster").status, "done");
  assert.equal(stage(view, "diagnose_cluster").endedAt, 400);
});

test("a retry updates the same row instead of adding one", () => {
  const view = run([
    started("diagnose_cluster", "c-1"),
    // The attempt hit a transient error: only its usage was written, so no counts.
    finished("diagnose_cluster", {}, { cluster_id: "c-1" }),
  ]);
  assert.equal(cluster(view, "c-1").status, "waiting");
  assert.equal(cluster(view, "c-1").endedAt, undefined);

  const again = run([started("diagnose_cluster", "c-1")], view);
  assert.equal(again.clusters.length, 1);
  assert.equal(cluster(again, "c-1").status, "running");
  assert.equal(cluster(again, "c-1").attempts, 2);

  const done = run(
    [finished("diagnose_cluster", { diagnoses: 1 }, { cluster_id: "c-1" })],
    again,
  );
  assert.equal(cluster(done, "c-1").status, "done");
  assert.equal(cluster(done, "c-1").attempts, 2);
});

test("a diagnosis that failed is a failed cluster, not a done one", () => {
  const view = run([
    started("cluster_failures"),
    finished("cluster_failures", { clusters: 1 }),
    started("diagnose_cluster", "c-1"),
    finished(
      "diagnose_cluster",
      { diagnosis_failures: 1 },
      { cluster_id: "c-1", ok: false },
    ),
  ]);
  assert.equal(cluster(view, "c-1").status, "failed");
  assert.equal(totals(view).failed, 1);
  assert.match(describeProgress(view), /1 failed/);
});

test("a failed node fails its stage and its cluster", () => {
  const view = run([
    started("diagnose_cluster", "c-1"),
    progress({
      event: "node_failed",
      node: "diagnose_cluster",
      cluster_id: "c-1",
    }),
  ]);
  assert.equal(stage(view, "diagnose_cluster").status, "failed");
  assert.equal(cluster(view, "c-1").status, "failed");
});

test("events that are not progress change nothing, and keep the same view", () => {
  const view = run([started("collect_traces")]);
  for (const kind of ["started", "completed", "failed", "unknown"] as const) {
    assert.equal(foldEvent(view, { kind }, 1), view);
  }
});

test("a node the view does not know is appended after the known ones", () => {
  const view = run([started("brand_new_node")]);
  const last = view.stages.at(-1);
  assert.equal(last?.node, "brand_new_node");
  assert.equal(last?.label, "brand new node");
  assert.equal(last?.status, "running");
});

test("only the diagnose node makes cluster rows", () => {
  const view = run([started("reproduce_failure", "c-1")]);
  assert.equal(view.clusters.length, 0);
});

test("a fold leaves untouched stages and rows as the same objects", () => {
  const before = run([
    started("diagnose_cluster", "c-1"),
    started("diagnose_cluster", "c-2"),
  ]);
  const after = run(
    [finished("diagnose_cluster", { diagnoses: 1 }, { cluster_id: "c-1" })],
    before,
  );
  assert.notEqual(cluster(after, "c-1"), cluster(before, "c-1"));
  assert.equal(cluster(after, "c-2"), cluster(before, "c-2"));
  assert.equal(stage(after, "collect_traces"), stage(before, "collect_traces"));
});

test("a stream cut early interrupts what was in flight", () => {
  const view = freezeView(
    run([
      started("collect_traces"),
      finished("collect_traces", { failed_traces: 4 }),
      started("diagnose_cluster", "c-1"),
      started("diagnose_cluster", "c-2"),
      finished("diagnose_cluster", { diagnoses: 1 }, { cluster_id: "c-1" }),
      finished("diagnose_cluster", {}, { cluster_id: "c-2" }),
      started("diagnose_cluster", "c-3"),
    ]),
    "lost",
  );
  assert.equal(cluster(view, "c-1").status, "done");
  assert.equal(cluster(view, "c-2").status, "interrupted"); // was waiting to retry
  assert.equal(cluster(view, "c-3").status, "interrupted");
  assert.equal(stage(view, "diagnose_cluster").status, "interrupted");
  // The run did not get to the later stages, so they are not "skipped".
  assert.equal(stage(view, "join_diagnoses").status, "pending");
});

test("a clean finish skips the stages the run never reached", () => {
  const view = freezeView(
    run([
      started("collect_traces"),
      finished("collect_traces", { failed_traces: 0 }),
    ]),
    "done",
  );
  assert.equal(stage(view, "collect_traces").status, "done");
  assert.equal(stage(view, "cluster_failures").status, "skipped");
});

test("describeProgress names the running stage before clusters are known", () => {
  assert.equal(describeProgress(INITIAL_VIEW), "");
  assert.equal(
    describeProgress(run([started("collect_traces")])),
    "Collect traces…",
  );
  assert.equal(
    describeProgress(
      run([
        started("collect_traces"),
        finished("collect_traces", { failed_traces: 3 }),
      ]),
    ),
    "3 failed traces found",
  );
});
