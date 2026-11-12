import assert from "node:assert/strict";
import { test } from "node:test";
import {
  badgeText,
  DOCK_STATUS,
  dockPhase,
  unreadCount,
  unreadText,
} from "./dock.ts";

test("messages count as unread only while the panel is closed", () => {
  assert.equal(unreadCount(5, 2, false), 3);
  assert.equal(unreadCount(5, 2, true), 0);
  // A new run's stream starts again below what was seen of the last one.
  assert.equal(unreadCount(1, 7, false), 0);
});

test("the badge shows the count, capped at 9+, and nothing for none", () => {
  assert.equal(badgeText(0), "");
  assert.equal(badgeText(3), "3");
  assert.equal(badgeText(9), "9");
  assert.equal(badgeText(12), "9+");
});

test("a screen reader hears the count as one phrase", () => {
  assert.equal(unreadText(0), "");
  assert.equal(unreadText(1), "1 new message in the agent console");
  assert.equal(unreadText(4), "4 new messages in the agent console");
});

test("every phase has words and a status tone", () => {
  for (const status of Object.values(DOCK_STATUS)) {
    assert.ok(status.label.length > 0 && status.line.length > 0);
  }
  assert.equal(DOCK_STATUS.running.tone, "info");
  assert.equal(DOCK_STATUS.review.tone, "warning");
});

test("a run paused at the review waits, though its stream is still open", () => {
  assert.equal(dockPhase("running", true), "review");
  assert.equal(dockPhase("running", false), "running");
  // Only a running stream is read again: an ended one already says how it ended.
  assert.equal(dockPhase("done", true), "done");
});
