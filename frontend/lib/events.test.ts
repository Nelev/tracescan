import assert from "node:assert/strict";
import { test } from "node:test";
import { foldEvent, isFailure, outcomeOf, parseRunEvent } from "./events.ts";

const progress = (data: unknown) =>
  parseRunEvent({ event: "progress", data: JSON.stringify(data) });
const uiSpec = (data: unknown) =>
  parseRunEvent({ event: "ui_spec", data: JSON.stringify(data) });

const SPEC = { root: "page", elements: {} };

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

test("a progress event is read only for whether its step failed", () => {
  const extra = { node: "a", task_id: "b", result: { secret: "span data" } };
  assert.deepEqual(progress({ event: "node_failed", ...extra }), {
    kind: "progress",
    failed: true,
  });
  for (const event of ["node_started", "node_finished"]) {
    assert.deepEqual(progress({ event, ...extra }), {
      kind: "progress",
      failed: false,
    });
  }
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
  assert.equal(isFailure(progress({ event: "node_failed" })), true);
  assert.equal(isFailure(progress({ event: "node_started" })), false);
  assert.equal(isFailure({ kind: "unknown" }), false);
});

test("only run_completed and run_failed end the run", () => {
  assert.equal(outcomeOf({ kind: "completed" }), "done");
  assert.equal(outcomeOf({ kind: "failed" }), "failed");
  assert.equal(outcomeOf({ kind: "started" }), null);
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
