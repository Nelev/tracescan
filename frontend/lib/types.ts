// Mirrors RunRequest in backend/api/schemas.py, the stream in backend/api/runs.py and the run list.

export type RunRequest = {
  target_app: string;
  since?: string; // timezone-aware ISO 8601, inclusive
  until?: string; // timezone-aware ISO 8601, exclusive
};

/** A run's status as GET /v1/runs reports it. */
export type RunStatus =
  | "in_progress"
  | "review_required"
  | "completed"
  | "failed"
  | "aborted";

/** One run in the list of GET /v1/runs (RunRecord in backend/runs/store.py): no state, no text. */
export type RunRecord = {
  run_id: string;
  target_app: string;
  since: string | null; // ISO 8601 with a timezone
  until: string | null;
  status: RunStatus;
  started_by: string | null; // a name, unverified; null for a run first recorded at its review
  created_at: string;
  ended_at: string | null;
  failed_traces: number;
  clusters: number;
  proposals: number;
};

/** What the reviewer answers per proposal (Decision in backend/agent/schemas.py). */
export type Decision = "approve" | "reject";

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
