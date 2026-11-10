import assert from "node:assert/strict";
import { test } from "node:test";
import { parseRunEvent } from "./events.ts";
import { foldEvent, freezeView, INITIAL_VIEW } from "./run-view.ts";

const SPEC = { root: "page", elements: {} };
const uiSpec = (data: unknown) =>
  parseRunEvent({ event: "ui_spec", data: JSON.stringify(data) });

test("a ui_spec payload is the message it is for and its spec", () => {
  assert.deepEqual(uiSpec({ event: "progress", spec: SPEC }), {
    kind: "ui_spec",
    ui: { event: "progress", spec: SPEC },
  });
});

test("a ui_spec off the contract is unknown, never a throw", () => {
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

test("each ui_spec becomes a message, in arrival order, with its position as id", () => {
  const first = uiSpec({ event: "run_started", spec: SPEC });
  const second = uiSpec({ event: "progress", spec: SPEC });
  const view = foldEvent(foldEvent(INITIAL_VIEW, first, 1), second, 2);
  assert.deepEqual(
    view.messages.map((m) => [m.id, m.event]),
    [
      [0, "run_started"],
      [1, "progress"],
    ],
  );
});

test("a progress event adds no message: only its ui_spec does", () => {
  const progress = parseRunEvent({
    event: "progress",
    data: JSON.stringify({
      event: "node_started",
      node: "collect_traces",
      task_id: "t1",
    }),
  });
  assert.deepEqual(foldEvent(INITIAL_VIEW, progress, 1).messages, []);
});

test("earlier messages keep their identity when a new one arrives", () => {
  const one = foldEvent(INITIAL_VIEW, uiSpec({ event: "a", spec: SPEC }), 1);
  const two = foldEvent(one, uiSpec({ event: "b", spec: SPEC }), 2);
  assert.equal(two.messages[0], one.messages[0]);
  assert.equal(two.stages, one.stages);
});

test("ending a run keeps its messages", () => {
  const view = foldEvent(INITIAL_VIEW, uiSpec({ event: "a", spec: SPEC }), 1);
  assert.deepEqual(freezeView(view, "done").messages, view.messages);
});
