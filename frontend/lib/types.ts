// Mirrors RunRequest in backend/api/schemas.py and the stream in backend/api/runs.py.

export type RunRequest = {
  target_app: string;
  since?: string; // timezone-aware ISO 8601, inclusive
  until?: string; // timezone-aware ISO 8601, exclusive
};

/**
 * Event names of POST /v1/runs/stream. `lib/events.ts` parses them into typed events: the console
 * draws the `ui_spec` ones, the UI spec the server's model wrote for the message just before it,
 * and the raw log lists them all.
 */
export const RUN_EVENTS = {
  started: "run_started",
  progress: "progress",
  // The run stopped at the human review: it waits for POST /v1/runs/{run_id}/review.
  reviewRequired: "review_required",
  // The run ended with nothing to review.
  completed: "run_completed",
  failed: "run_failed",
  uiSpec: "ui_spec",
} as const;
