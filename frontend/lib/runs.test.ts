import assert from "node:assert/strict";
import { test } from "node:test";
import {
  formatWhen,
  formatWindow,
  parseRuns,
  RUN_STATUS,
  shortId,
} from "./runs.ts";

const RUN = {
  run_id: "3f9a1c2e-0000-4000-8000-000000000000",
  target_app: "medas",
  since: "2026-11-05T09:00:00Z",
  until: null,
  status: "review_required",
  started_by: "ana",
  created_at: "2026-11-10T14:32:05Z",
  ended_at: null,
  failed_traces: 12,
  clusters: 3,
  proposals: 3,
};

const utc = (iso: string) => formatWhen(iso, "en-GB", "UTC");

test("a run on contract is kept as it is", () => {
  assert.deepEqual(parseRuns([RUN]), [RUN]);
});

test("a run nobody started keeps its null name", () => {
  const [run] = parseRuns([{ ...RUN, started_by: null }]);
  assert.equal(run.started_by, null);
});

test("a row that is off contract is left out and the others stay", () => {
  const rows = [
    RUN,
    { ...RUN, status: "exploded" },
    { ...RUN, status: "toString" }, // a property every object has is not a status
    { ...RUN, clusters: "3" },
    { ...RUN, created_at: undefined },
    null,
    "run",
  ];
  assert.deepEqual(parseRuns(rows), [RUN]);
});

test("a body that is not a list is no runs, not an error", () => {
  for (const body of [null, undefined, {}, "runs", { detail: "boom" }]) {
    assert.deepEqual(parseRuns(body), []);
  }
});

test("every status the server can send has a label", () => {
  const sent = [
    "in_progress",
    "review_required",
    "completed",
    "failed",
    "aborted",
  ];
  assert.deepEqual(Object.keys(RUN_STATUS).sort(), sent.sort());
  for (const status of sent) {
    assert.equal(parseRuns([{ ...RUN, status }]).length, 1);
  }
});

test("only a run that waits for its review asks for attention", () => {
  const tones = Object.fromEntries(
    Object.entries(RUN_STATUS).map(([status, { tone }]) => [status, tone]),
  );
  assert.deepEqual(tones, {
    in_progress: "info",
    review_required: "warning",
    completed: "success",
    failed: "destructive",
    aborted: "stopped",
  });
});

test("a run id is shortened to its first group", () => {
  assert.equal(shortId(RUN.run_id), "3f9a1c2e");
});

test("a timestamp reads as day, month and time", () => {
  assert.equal(utc("2026-11-10T14:32:05Z"), "10 Nov, 14:32");
  assert.equal(utc("2026-11-10T00:05:00+01:00"), "9 Nov, 23:05");
});

test("a timestamp that cannot be read is shown as it came", () => {
  assert.equal(formatWhen("soon"), "soon");
});

test("a window names the ends it has", () => {
  const since = "2026-11-05T09:00:00Z";
  const until = "2026-11-06T09:00:00Z";
  assert.equal(formatWindow(null, null, utc), "All time");
  assert.equal(formatWindow(since, null, utc), "From 5 Nov, 09:00");
  assert.equal(formatWindow(null, until, utc), "Until 6 Nov, 09:00");
  assert.equal(formatWindow(since, until, utc), "5 Nov, 09:00 → 6 Nov, 09:00");
});
