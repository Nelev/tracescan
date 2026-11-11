import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDuration } from "./format.ts";
import {
  blamedBy,
  formatScore,
  formatValue,
  parseTraceDetail,
  parseTraces,
  spanKind,
  traceVerdict,
  waterfall,
} from "./traces.ts";

const ROW = {
  trace_id: "0af7651916cd43dd8448eb211c80319c",
  start_time: "2026-10-26T07:33:20.123456Z",
  duration_ms: 2000,
  status: "unset",
  spans: 2,
  min_score: 0,
  failed: true,
  failing_span_id: "00f067aa0ba902b7",
  failing_span_name: "retrieval",
  failing_check: "tool_error",
  error_type: "EmptyRetrieval",
};

const CHILD = {
  span_id: "00f067aa0ba902b7",
  trace_id: ROW.trace_id,
  parent_span_id: "b7ad6b7169203331",
  name: "retrieval",
  kind: "unspecified",
  start_time: "2026-10-26T07:33:20.500Z",
  end_time: "2026-10-26T07:33:21.000Z",
  status: "error",
  status_message: "no documents",
  attributes: { "gen_ai.system": "openrouter", tags: "[redacted]" },
  events: [
    {
      name: "exception",
      time: "2026-10-26T07:33:20.900Z",
      attributes: { "exception.type": "EmptyRetrieval" },
    },
  ],
  children: [],
};

const DETAIL = {
  trace_id: ROW.trace_id,
  tree: {
    span_id: "b7ad6b7169203331",
    trace_id: ROW.trace_id,
    parent_span_id: null,
    name: "request",
    kind: "server",
    start_time: "2026-10-26T07:33:20.000Z",
    end_time: "2026-10-26T07:33:22.000Z",
    status: "unset",
    status_message: null,
    attributes: {},
    events: [],
    children: [CHILD],
  },
  scores: [
    { evaluator: "request_failed", value: 1, span_id: null, failed: false },
    {
      evaluator: "tool_error",
      value: 0,
      span_id: CHILD.span_id,
      failed: true,
    },
  ],
  min_score: 0,
  failed: true,
};

test("a trace row on contract is kept, an off-contract one is left out", () => {
  assert.deepEqual(parseTraces([ROW]), [ROW]);
  assert.deepEqual(parseTraces([ROW, { ...ROW, spans: "2" }, null]), [ROW]);
  assert.deepEqual(parseTraces({ rows: [ROW] }), []);
});

test("a trace detail is read whole, with its tree", () => {
  const detail = parseTraceDetail(DETAIL);
  assert.ok(detail);
  assert.equal(detail.tree.children[0].status_message, "no documents");
  assert.deepEqual(detail.tree.children[0].events[0].attributes, {
    "exception.type": "EmptyRetrieval",
  });
});

test("one bad span makes the whole detail unreadable", () => {
  const badChild = { ...CHILD, status: "broken" };
  assert.equal(
    parseTraceDetail({
      ...DETAIL,
      tree: { ...DETAIL.tree, children: [badChild] },
    }),
    null,
  );
  assert.equal(parseTraceDetail({ ...DETAIL, scores: [{}] }), null);
  const noEvents = { ...CHILD, events: undefined };
  assert.equal(
    parseTraceDetail({
      ...DETAIL,
      tree: { ...DETAIL.tree, children: [noEvents] },
    }),
    null,
  );
  assert.equal(parseTraceDetail(null), null);
});

test("the verdict comes from the scores", () => {
  assert.equal(
    traceVerdict({ failed: true, min_score: 0 }).tone,
    "destructive",
  );
  assert.equal(traceVerdict({ failed: false, min_score: 1 }).label, "Passed");
  assert.equal(
    traceVerdict({ failed: false, min_score: null }).label,
    "Unscored",
  );
});

test("the waterfall places each span on the root's timeline, in reading order", () => {
  const detail = parseTraceDetail(DETAIL);
  assert.ok(detail);
  const [root, child] = waterfall(detail.tree);
  assert.deepEqual(
    [root.depth, root.offsetMs, root.durationMs, root.left, root.width],
    [0, 0, 2000, 0, 1],
  );
  assert.deepEqual(
    [child.depth, child.offsetMs, child.durationMs, child.left, child.width],
    [1, 500, 500, 0.25, 0.25],
  );
});

test("a span outside the root's time is clamped to the bar", () => {
  const late = {
    ...CHILD,
    start_time: "2026-10-26T07:33:21.500Z",
    end_time: "2026-10-26T07:33:23.000Z",
  };
  const detail = parseTraceDetail({
    ...DETAIL,
    tree: { ...DETAIL.tree, children: [late] },
  });
  assert.ok(detail);
  const [, row] = waterfall(detail.tree);
  assert.deepEqual([row.left, row.width], [0.75, 0.25]);
});

test("only failed scores blame a span", () => {
  assert.deepEqual(
    [...blamedBy(DETAIL.scores)],
    [[CHILD.span_id, ["tool_error"]]],
  );
});

test("durations, scores and values read short", () => {
  assert.equal(formatDuration(840.4), "840 ms");
  assert.equal(formatDuration(2400), "2.4 s");
  assert.equal(formatDuration(12_400), "12 s");
  assert.equal(formatDuration(65_000), "1 min 5 s");
  assert.equal(formatScore(null), "—");
  assert.equal(formatScore(0.5), "0.50");
  assert.equal(formatValue("a"), "a");
  assert.equal(formatValue(3), "3");
  assert.equal(formatValue(["a", true]), '["a",true]');
});

test("a span's kind comes from the first word of its name", () => {
  assert.equal(spanKind("invoke_agent medas"), "agent");
  assert.equal(spanKind("chat claude-sonnet"), "chat");
  assert.equal(spanKind("execute_tool search_records"), "tool");
  assert.equal(spanKind("retrieval record_chunks"), "retrieval");
  assert.equal(spanKind("chatter"), "other");
  assert.equal(spanKind(""), "other");
});
