// Mirrors RunRequest in backend/api/schemas.py and the stream in backend/api/runs.py.

export type RunRequest = {
  target_app: string;
  since?: string; // timezone-aware ISO 8601, inclusive
  until?: string; // timezone-aware ISO 8601, exclusive
};

/**
 * Event names of POST /v1/runs/stream. `lib/events.ts` parses them into typed events: the
 * progress view reads the progress events, and the console draws the `ui_spec` ones, the UI spec
 * the server's model wrote for the message just before it.
 */
export const RUN_EVENTS = {
  started: "run_started",
  progress: "progress",
  completed: "run_completed",
  failed: "run_failed",
  uiSpec: "ui_spec",
} as const;
