import assert from "node:assert/strict";
import { test } from "node:test";
import {
  formatRunTime,
  formatScore,
  headline,
  metricsFor,
  parseEvalRuns,
  runsOf,
  runTime,
  series,
} from "./eval.ts";

const run = (id: string, experiment: string, scores: object) => ({
  id,
  experiment,
  model: "m",
  judge_model: "j",
  graded: true,
  scores,
});

const RAW = [
  run("20261110T163822Z", "seeded", {
    detection: { hits: 5, total: 8 },
    false_alarms: 1,
  }),
  run("20261114T074549Z", "seeded", {
    detection: { hits: 8, total: 8 },
    cause_accuracy: { hits: 8, total: 9 },
    judge_recall: { hits: 34, total: 34 },
    false_alarms: 0,
    cost_usd: 0.1778,
    seconds: 25.5,
  }),
  run("20261114T074605Z", "control", {
    detection: { hits: 0, total: 0 },
    judge_false_positives: { hits: 0, total: 52 },
    false_alarms: 0,
    cost_usd: 0.0277,
  }),
  run("bad id", "seeded", {}),
  run("20261114T074606Z", "elsewhere", {}),
  { id: "20261114T074607Z", experiment: "seeded" },
];

test("the export parses to runs in its order, leaving off-contract rows out", () => {
  const runs = parseEvalRuns(RAW);
  assert.deepEqual(
    runs.map((r) => r.id),
    ["20261110T163822Z", "20261114T074549Z", "20261114T074605Z"],
  );
  assert.equal(runs[1].judgeModel, "j");
  assert.deepEqual(parseEvalRuns({ not: "a list" }), []);
});

test("a score that is neither a ratio nor a number is dropped", () => {
  const [r] = parseEvalRuns([
    run("20261114T074549Z", "seeded", {
      a: { hits: 1 },
      b: "x",
      c: 2,
      d: { hits: 1.5, total: 2 },
    }),
  ]);
  assert.deepEqual(r.scores, { c: 2 });
});

test("a run id reads as its UTC start", () => {
  assert.equal(runTime("20261114T074549Z"), "2026-11-14T07:45:49Z");
  assert.equal(formatRunTime("20261114T074549Z"), "14 Nov, 07:45 UTC");
});

test("a metric's series is its share per run, null where it was not scored", () => {
  const seeded = runsOf(parseEvalRuns(RAW), "seeded");
  assert.deepEqual(series(seeded, "detection"), [5 / 8, 1]);
  assert.deepEqual(series(seeded, "cause_accuracy"), [null, 8 / 9]);
  assert.deepEqual(series(seeded, "false_alarms"), [1, 0]);
});

test("rows are the metrics the newest run scored, so a control day has no detection", () => {
  const runs = parseEvalRuns(RAW);
  assert.deepEqual(
    metricsFor(runsOf(runs, "seeded")).map((m) => m.key),
    ["judge_recall", "detection", "cause_accuracy", "false_alarms"],
  );
  assert.deepEqual(
    metricsFor(runsOf(runs, "control")).map((m) => m.key),
    ["judge_false_positives", "false_alarms"],
  );
  assert.deepEqual(metricsFor([]), []);
});

test("scores read as hits over total or a plain count", () => {
  assert.equal(formatScore({ hits: 8, total: 9 }), "8/9");
  assert.equal(formatScore(0), "0");
});

test("the headline of a seeded run leads with cause accuracy, a control day with false alarms", () => {
  const runs = parseEvalRuns(RAW);
  assert.deepEqual(
    headline(runs[1]).map((t) => [t.label, t.value]),
    [
      ["Cause accuracy", "89%"],
      ["Detection", "100%"],
      ["Judge recall", "100%"],
      ["Cost", "$0.18"],
    ],
  );
  assert.deepEqual(
    headline(runs[2]).map((t) => [t.label, t.value]),
    [
      ["False alarms", "0"],
      ["Judge false positives", "0%"],
      ["Cost", "$0.03"],
    ],
  );
});
