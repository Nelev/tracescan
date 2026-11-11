import assert from "node:assert/strict";
import { test } from "node:test";
import { foldEvent, isFailure, outcomeOf, parseRunEvent } from "./events.ts";

const progress = (data: unknown) =>
  parseRunEvent({ event: "progress", data: JSON.stringify(data) });
const uiSpec = (data: unknown) =>
  parseRunEvent({ event: "ui_spec", data: JSON.stringify(data) });

const SPEC = { root: "page", elements: {} };

test("run_started names the run, and the other lifecycle events carry no payload", () => {
  assert.deepEqual(
    parseRunEvent({ event: "run_started", data: '{"run_id":"3f9a1c2e"}' }),
    { kind: "started", runId: "3f9a1c2e" },
  );
  for (const data of ["{}", '{"run_id":7}', "not json"]) {
    assert.deepEqual(parseRunEvent({ event: "run_started", data }), {
      kind: "started",
      runId: null,
    });
  }
  assert.deepEqual(parseRunEvent({ event: "run_completed", data: "{}" }), {
    kind: "completed",
  });
  assert.deepEqual(parseRunEvent({ event: "run_failed", data: "{}" }), {
    kind: "failed",
  });
});

test("a progress event keeps its node, cluster and counts, never its result", () => {
  const extra = { node: "a", task_id: "b", result: { secret: "span data" } };
  const read = (event: string, more = {}) =>
    progress({ event, ...extra, ...more });
  assert.deepEqual(read("node_failed"), {
    kind: "progress",
    progress: {
      event: "node_failed",
      node: "a",
      clusterId: null,
      ok: true,
      counts: {},
    },
  });
  for (const event of ["node_started", "node_finished"]) {
    const parsed = read(event);
    assert.equal(isFailure(parsed), false);
  }
  const branch = read("node_finished", {
    cluster_id: "c1",
    ok: false,
    counts: { diagnoses: 0, junk: "x" },
  });
  assert.ok(branch.kind === "progress");
  assert.deepEqual(branch.progress, {
    event: "node_finished",
    node: "a",
    clusterId: "c1",
    ok: false,
    counts: { diagnoses: 0 },
  });
  assert.deepEqual(read("node_exploded"), { kind: "unknown" });
});

test("a ui_spec payload is the message it is for and its spec", () => {
  assert.deepEqual(uiSpec({ event: "progress", spec: SPEC }), {
    kind: "ui_spec",
    ui: { event: "progress", spec: SPEC },
  });
});

test("anything off-contract is unknown, never a throw", () => {
  assert.deepEqual(parseRunEvent({ event: "progress", data: "{not json" }), {
    kind: "unknown",
  });
  assert.deepEqual(progress([1, 2]), { kind: "unknown" });
  assert.deepEqual(parseRunEvent({ event: "something_new", data: "{}" }), {
    kind: "unknown",
  });
  assert.deepEqual(uiSpec({ event: "progress", spec: "page" }), {
    kind: "unknown",
  });
  assert.deepEqual(uiSpec({ event: "progress", spec: [1] }), {
    kind: "unknown",
  });
  assert.deepEqual(uiSpec({ spec: SPEC }), { kind: "unknown" });
  assert.deepEqual(parseRunEvent({ event: "ui_spec", data: "{nope" }), {
    kind: "unknown",
  });
});

test("isFailure is run_failed or a failed step", () => {
  assert.equal(isFailure({ kind: "failed" }), true);
  assert.equal(isFailure(progress({ event: "node_failed", node: "a" })), true);
  assert.equal(
    isFailure(progress({ event: "node_started", node: "a" })),
    false,
  );
  assert.equal(isFailure({ kind: "unknown" }), false);
});

test("review_required is a run that waits for its review", () => {
  const event = parseRunEvent({ event: "review_required", data: "{}" });
  assert.deepEqual(event, { kind: "review" });
  assert.equal(isFailure(event), false);
});

test("only review_required, run_completed and run_failed end the stream", () => {
  assert.equal(outcomeOf({ kind: "review" }), "review");
  assert.equal(outcomeOf({ kind: "completed" }), "done");
  assert.equal(outcomeOf({ kind: "failed" }), "failed");
  assert.equal(outcomeOf({ kind: "started", runId: null }), null);
  assert.equal(outcomeOf({ kind: "unknown" }), null);
  assert.equal(outcomeOf(progress({ event: "node_failed" })), null);
});

test("each ui_spec becomes a message, in arrival order, with its position as id", () => {
  const first = uiSpec({ event: "run_started", spec: SPEC });
  const second = uiSpec({ event: "progress", spec: SPEC });
  const messages = foldEvent(foldEvent([], first), second);
  assert.deepEqual(
    messages.map((m) => [m.id, m.event]),
    [
      [0, "run_started"],
      [1, "progress"],
    ],
  );
});

test("an event that is not a ui_spec adds no message", () => {
  const before = foldEvent([], uiSpec({ event: "a", spec: SPEC }));
  // The same array, not a copy, so earlier messages keep their identity.
  assert.equal(foldEvent(before, progress({ event: "node_started" })), before);
});
