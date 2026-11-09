// Mirrors RunRequest / RunResponse in backend/api/schemas.py.

export type RunRequest = {
  target_app: string;
  since?: string; // timezone-aware ISO 8601, inclusive
  until?: string; // timezone-aware ISO 8601, exclusive
};

export type RunResponse = {
  run_id: string;
  failed_traces: number;
  clusters: number;
  unclustered: number; // failures that fit no cluster; kept, not diagnosed
  diagnoses: number;
  diagnosis_failures: number; // clusters whose diagnosis failed; reported, not dropped
  proposals: number;
  actions_log: string[];
};
