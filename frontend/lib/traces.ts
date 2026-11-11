// The stored traces of GET /v1/traces and GET /v1/traces/{id}: read once into typed values, and
// what the trace pages draw from them. Mirrors api/schemas.py and trace_store/models.py by hand.

import { isRecord as isObj } from "./guards.ts";
import { isText, isTextOrNull, type StatusTone } from "./runs.ts";

/** What the server puts in place of an attribute outside its allowlist (trace_store/const.py). */
export const REDACTED = "[redacted]";

export type SpanStatus = "unset" | "ok" | "error";

/** One trace in the list: its root span, its spans and its lowest score. */
export type TraceRow = {
  trace_id: string;
  /** The target app that sent it. */
  app: string;
  start_time: string;
  duration_ms: number;
  status: SpanStatus;
  spans: number;
  /** Null: not scored yet. */
  min_score: number | null;
  failed: boolean;
  // Set for a failed trace only: names, never a message.
  failing_span_id: string | null;
  failing_span_name: string | null;
  failing_check: string | null;
  error_type: string | null;
};

/** One check's score: 0 bad, 1 fine. A bad (`failed`) score blames a span. */
export type TraceScore = {
  evaluator: string;
  value: number;
  span_id: string | null;
  /** Set by the server, which owns the threshold. */
  failed: boolean;
};

export type SpanEvent = {
  name: string;
  time: string | null;
  attributes: Record<string, unknown>;
};

/** A span as the server sends it: attributes outside its allowlist already redacted. */
export type SpanNode = {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: string;
  start_time: string;
  end_time: string;
  status: SpanStatus;
  status_message: string | null;
  attributes: Record<string, unknown>;
  events: SpanEvent[];
  children: SpanNode[];
};

export type TraceDetail = {
  trace_id: string;
  app: string;
  tree: SpanNode;
  scores: TraceScore[];
  min_score: number | null;
  failed: boolean;
};

export const isNum = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);
const isNumOrNull = (v: unknown): v is number | null => v === null || isNum(v);
const isStatus = (v: unknown): v is SpanStatus =>
  v === "unset" || v === "ok" || v === "error";

function isRow(v: unknown): v is TraceRow {
  return (
    isObj(v) &&
    isText(v.trace_id) &&
    isText(v.app) &&
    isText(v.start_time) &&
    isNum(v.duration_ms) &&
    isStatus(v.status) &&
    Number.isInteger(v.spans) &&
    isNumOrNull(v.min_score) &&
    typeof v.failed === "boolean" &&
    isTextOrNull(v.failing_span_id) &&
    isTextOrNull(v.failing_span_name) &&
    isTextOrNull(v.failing_check) &&
    isTextOrNull(v.error_type)
  );
}

/** The rows of a list body that are on contract; anything else is left out, never thrown. */
export function parseTraces(body: unknown): TraceRow[] {
  return Array.isArray(body) ? body.filter(isRow) : [];
}

function isScore(v: unknown): v is TraceScore {
  return (
    isObj(v) &&
    isText(v.evaluator) &&
    isNum(v.value) &&
    isTextOrNull(v.span_id) &&
    typeof v.failed === "boolean"
  );
}

function isEvent(v: unknown): v is SpanEvent {
  return (
    isObj(v) && isText(v.name) && isTextOrNull(v.time) && isObj(v.attributes)
  );
}

/** The whole tree as the server sends it; one span off contract fails it all. */
function isSpan(v: unknown): v is SpanNode {
  return (
    isObj(v) &&
    isText(v.span_id) &&
    isTextOrNull(v.parent_span_id) &&
    isText(v.name) &&
    isText(v.kind) &&
    isText(v.start_time) &&
    isText(v.end_time) &&
    isStatus(v.status) &&
    isTextOrNull(v.status_message) &&
    isObj(v.attributes) &&
    Array.isArray(v.events) &&
    v.events.every(isEvent) &&
    Array.isArray(v.children) &&
    v.children.every(isSpan)
  );
}

/** One trace, or null when any part of it is off contract: never half a tree. */
export function parseTraceDetail(body: unknown): TraceDetail | null {
  if (
    !isObj(body) ||
    !isText(body.trace_id) ||
    !isText(body.app) ||
    !Array.isArray(body.scores) ||
    !body.scores.every(isScore) ||
    !isNumOrNull(body.min_score) ||
    typeof body.failed !== "boolean" ||
    !isSpan(body.tree)
  ) {
    return null;
  }
  return {
    trace_id: body.trace_id,
    app: body.app,
    tree: body.tree,
    scores: body.scores,
    min_score: body.min_score,
    failed: body.failed,
  };
}

/** A trace's page, opened on `spanId` when one is given. */
export const tracePath = (traceId: string, spanId: string | null = null) =>
  `/traces/${encodeURIComponent(traceId)}${spanId ? `?span=${encodeURIComponent(spanId)}` : ""}`;

/** A trace's verdict in the list and the viewer: its scores decide, not its error spans. */
export function traceVerdict(t: {
  failed: boolean;
  min_score: number | null;
}): { label: string; tone: StatusTone } {
  if (t.failed) return { label: "Failed", tone: "destructive" };
  if (t.min_score === null) return { label: "Unscored", tone: "neutral" };
  return { label: "Passed", tone: "success" };
}

/** One span as a row of the waterfall: where it sits in the tree and on the root's timeline. */
export type WaterfallRow = {
  span: SpanNode;
  depth: number;
  /** From the root's start, and how long it took (ms). */
  offsetMs: number;
  durationMs: number;
  /** The same, as fractions of the root's duration, clamped to [0, 1]. */
  left: number;
  width: number;
};

const ms = (iso: string) => new Date(iso).getTime();
const clamp = (x: number) => Math.min(1, Math.max(0, x));

/** The tree in reading order (each span before its children), placed on the root's timeline. */
export function waterfall(root: SpanNode): WaterfallRow[] {
  const t0 = ms(root.start_time);
  const total = Math.max(ms(root.end_time) - t0, 1);
  const rows: WaterfallRow[] = [];
  const walk = (span: SpanNode, depth: number) => {
    const offsetMs = ms(span.start_time) - t0;
    const durationMs = Math.max(ms(span.end_time) - ms(span.start_time), 0);
    const left = clamp(offsetMs / total);
    rows.push({
      span,
      depth,
      offsetMs,
      durationMs,
      left,
      width: Math.min(clamp(durationMs / total), 1 - left),
    });
    for (const child of span.children) walk(child, depth + 1);
  };
  walk(root, 0);
  return rows;
}

/** For each span the failed scores blame, the checks that blame it. */
export function blamedBy(scores: TraceScore[]): Map<string, string[]> {
  const blamed = new Map<string, string[]>();
  for (const s of scores) {
    if (s.span_id === null || !s.failed) continue;
    const checks = blamed.get(s.span_id);
    if (checks) checks.push(s.evaluator);
    else blamed.set(s.span_id, [s.evaluator]);
  }
  return blamed;
}

/** A score as shown: two decimals, or a dash when there is none. */
export function formatScore(score: number | null): string {
  return score === null ? "—" : score.toFixed(2);
}

/** An attribute value as one line of text. */
export function formatValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "null";
  return JSON.stringify(value);
}

/** What a span does, from its name (the gen_ai span names Medas emits). */
export type SpanKind = "agent" | "chat" | "tool" | "retrieval" | "other";

const KIND_PREFIX: [string, SpanKind][] = [
  ["invoke_agent", "agent"],
  ["chat", "chat"],
  ["execute_tool", "tool"],
  ["retrieval", "retrieval"],
];

export function spanKind(name: string): SpanKind {
  const first = name.split(" ", 1)[0];
  return KIND_PREFIX.find(([prefix]) => first === prefix)?.[1] ?? "other";
}
