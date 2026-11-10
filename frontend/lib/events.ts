import type { SseMessage } from "./sse.ts";
import { RUN_EVENTS } from "./types.ts";

/** Mirrors `ProgressEvent` in backend/agent/progress.py: ids and counts only, never span data. */
export type ProgressEvent = {
  event: (typeof PROGRESS_EVENTS)[number];
  node: string;
  task_id: string;
  /** Set on the branches of the diagnose fan-out. */
  cluster_id?: string;
  /** False when a node finished but recorded a failure (a cluster whose diagnosis failed). */
  ok?: boolean;
  counts?: Record<string, number>;
};

/**
 * One stream message, parsed once at the edge. Anything that does not match the contract becomes
 * `unknown`: the raw console still prints it, and the progress view ignores it.
 */
export type RunEvent =
  | { kind: "started" }
  | { kind: "progress"; progress: ProgressEvent }
  | { kind: "completed" }
  | { kind: "failed" }
  | { kind: "ui_spec"; ui: UiSpecEvent }
  | { kind: "unknown" };

/**
 * Mirrors the `ui_spec` event of backend/api/runs.py: the json-render spec the server's model
 * wrote for one message, and the name of that message (`progress`, `proposal`, ...). The spec is
 * unchecked here: it is whatever the model replied, and lib/ui-catalog.ts checks it before it is
 * drawn.
 */
export type UiSpecEvent = { event: string; spec: Record<string, unknown> };

const UNKNOWN: RunEvent = { kind: "unknown" };

const PROGRESS_EVENTS = [
  "node_started",
  "node_finished",
  "node_failed",
] as const;

const isProgressName = (value: unknown): value is ProgressEvent["event"] =>
  PROGRESS_EVENTS.some((name) => name === value);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toProgress(data: unknown): ProgressEvent | null {
  if (!isRecord(data)) return null;
  const { event, node, task_id, cluster_id, ok, counts } = data;
  if (!isProgressName(event)) return null;
  if (typeof node !== "string" || typeof task_id !== "string") return null;

  const progress: ProgressEvent = { event, node, task_id };
  if (typeof cluster_id === "string") progress.cluster_id = cluster_id;
  if (typeof ok === "boolean") progress.ok = ok;
  if (isRecord(counts)) {
    progress.counts = Object.fromEntries(
      Object.entries(counts).filter(
        (entry): entry is [string, number] => typeof entry[1] === "number",
      ),
    );
  }
  return progress;
}

/** A message's data as JSON, or undefined when it is not: the callers refuse non-objects anyway. */
function parseData(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

export function parseRunEvent(message: SseMessage): RunEvent {
  switch (message.event) {
    case RUN_EVENTS.started:
      return { kind: "started" };
    case RUN_EVENTS.completed:
      return { kind: "completed" };
    case RUN_EVENTS.failed:
      return { kind: "failed" };
    case RUN_EVENTS.progress: {
      const progress = toProgress(parseData(message.data));
      return progress ? { kind: "progress", progress } : UNKNOWN;
    }
    case RUN_EVENTS.uiSpec: {
      const data = parseData(message.data);
      if (!isRecord(data) || !isRecord(data.spec)) return UNKNOWN;
      if (typeof data.event !== "string") return UNKNOWN;
      return { kind: "ui_spec", ui: { event: data.event, spec: data.spec } };
    }
    default:
      return UNKNOWN;
  }
}

/** How the run ended, if this event ends it. */
export function outcomeOf(event: RunEvent): "done" | "failed" | null {
  if (event.kind === "completed") return "done";
  return event.kind === "failed" ? "failed" : null;
}
