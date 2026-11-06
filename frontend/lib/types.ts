// Mirrors RunRequest / RunResponse in backend/api/runs.py.

export type RunRequest = {
  target_app: string;
  since?: string; // timezone-aware ISO 8601, inclusive
  until?: string; // timezone-aware ISO 8601, exclusive
};

export type RunResponse = {
  run_id: string;
  failed_traces: number;
  clusters: number;
  diagnoses: number;
  proposals: number;
  actions_log: string[];
};
