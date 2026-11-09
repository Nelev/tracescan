import type { SseMessage } from "./sse";

// Mirrors RunRequest in backend/api/schemas.py and the stream in backend/api/runs.py.

export type RunRequest = {
  target_app: string;
  since?: string; // timezone-aware ISO 8601, inclusive
  until?: string; // timezone-aware ISO 8601, exclusive
};

/**
 * Event names of POST /v1/runs/stream. The console prints each event's data as received; the
 * only payload field read is `event` of a `progress` payload (agent.progress.ProgressEvent), to
 * spot a failed node.
 */
export const RUN_EVENTS = {
  started: "run_started",
  progress: "progress",
  completed: "run_completed",
  failed: "run_failed",
} as const;

/** How the run ended, if `event` ends it. */
export function runOutcome(event: string): "done" | "failed" | null {
  if (event === RUN_EVENTS.completed) return "done";
  if (event === RUN_EVENTS.failed) return "failed";
  return null;
}

/** True for run_failed and for a progress event that reports a failed node. */
export function isFailure(message: SseMessage): boolean {
  if (message.event === RUN_EVENTS.failed) return true;
  if (message.event !== RUN_EVENTS.progress) return false;
  try {
    return JSON.parse(message.data).event === "node_failed";
  } catch {
    return false;
  }
}
