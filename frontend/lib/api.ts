import type { RunRequest, RunResponse } from "./types";

/** A failed run. `status` is null when the backend could not be reached at all. */
export class RunError extends Error {
  constructor(readonly status: number | null) {
    super(status === null ? "unreachable" : `http ${status}`);
  }
}

export async function runTriage(
  body: RunRequest,
  signal: AbortSignal,
): Promise<RunResponse> {
  let res: Response;
  try {
    res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new RunError(null);
  }
  if (!res.ok) throw new RunError(res.status);
  return res.json();
}

export async function checkHealth(signal: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch("/api/health", { signal });
    return res.ok;
  } catch {
    return false;
  }
}
