import assert from "node:assert/strict";
import { test } from "node:test";
import { outcomeOf, parseRunEvent } from "./events.ts";

const progress = (data: unknown) =>
  parseRunEvent({ event: "progress", data: JSON.stringify(data) });

test("lifecycle events carry no payload", () => {
  assert.deepEqual(parseRunEvent({ event: "run_started", data: "{}" }), {
    kind: "started",
  });
  assert.deepEqual(parseRunEvent({ event: "run_completed", data: "{}" }), {
    kind: "completed",
  });
  assert.deepEqual(parseRunEvent({ event: "run_failed", data: "{}" }), {
    kind: "failed",
  });
});

test("a progress payload is read field by field", () => {
  const event = progress({
    event: "node_finished",
    node: "diagnose_cluster",
    task_id: "t1",
    cluster_id: "c-1",
    ok: false,
    counts: { diagnoses: 1, junk: "x" },
    result: { secret: "span data" },
  });
  assert.deepEqual(event, {
    kind: "progress",
    progress: {
      event: "node_finished",
      node: "diagnose_cluster",
      task_id: "t1",
      cluster_id: "c-1",
      ok: false,
      // Non-numeric counts are dropped, and unknown fields never get through.
      counts: { diagnoses: 1 },
    },
  });
});

test("anything off-contract is unknown, never a throw", () => {
  assert.deepEqual(parseRunEvent({ event: "progress", data: "{not json" }), {
    kind: "unknown",
  });
  assert.deepEqual(progress([1, 2]), { kind: "unknown" });
  assert.deepEqual(
    progress({ event: "node_exploded", node: "a", task_id: "b" }),
    {
      kind: "unknown",
    },
  );
  assert.deepEqual(progress({ event: "node_started", node: "a" }), {
    kind: "unknown",
  });
  assert.deepEqual(parseRunEvent({ event: "something_new", data: "{}" }), {
    kind: "unknown",
  });
});

test("only run_completed and run_failed end the run", () => {
  assert.equal(outcomeOf({ kind: "completed" }), "done");
  assert.equal(outcomeOf({ kind: "failed" }), "failed");
  assert.equal(outcomeOf({ kind: "started" }), null);
  assert.equal(outcomeOf({ kind: "unknown" }), null);
  assert.equal(
    outcomeOf(progress({ event: "node_failed", node: "a", task_id: "b" })),
    null,
  );
});
