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
  | { kind: "unknown" };

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

export function parseRunEvent(message: SseMessage): RunEvent {
  switch (message.event) {
    case RUN_EVENTS.started:
      return { kind: "started" };
    case RUN_EVENTS.completed:
      return { kind: "completed" };
    case RUN_EVENTS.failed:
      return { kind: "failed" };
    case RUN_EVENTS.progress: {
      let data: unknown;
      try {
        data = JSON.parse(message.data);
      } catch {
        return UNKNOWN;
      }
      const progress = toProgress(data);
      return progress ? { kind: "progress", progress } : UNKNOWN;
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

/** True for run_failed and for a progress event that reports a failed node. */
export function isFailure(event: RunEvent): boolean {
  return (
    event.kind === "failed" ||
    (event.kind === "progress" && event.progress.event === "node_failed")
  );
}
