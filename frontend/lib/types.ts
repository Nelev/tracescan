// Mirrors RunRequest in backend/api/schemas.py and the stream in backend/api/runs.py.

export type RunRequest = {
  target_app: string;
  since?: string; // timezone-aware ISO 8601, inclusive
  until?: string; // timezone-aware ISO 8601, exclusive
};

/**
 * Event names of POST /v1/runs/stream. The console prints each event's data as received;
 * `lib/events.ts` parses them into typed events for the progress view.
 */
export const RUN_EVENTS = {
  started: "run_started",
  progress: "progress",
  completed: "run_completed",
  failed: "run_failed",
} as const;
