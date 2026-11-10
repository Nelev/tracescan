import { parseRuns } from "./runs";
import { readSse, type SseMessage } from "./sse";
import type { RunRecord, RunRequest } from "./types";

/** A run that could not start. `status` is null when the backend could not be reached at all. */
export class RunError extends Error {
  constructor(readonly status: number | null) {
    super(status === null ? "unreachable" : `http ${status}`);
  }
}

export const RUN_STREAM_PATH = "/api/runs/stream";

export type RunStream = {
  status: number;
  contentType: string;
  /** The run's events as they arrive. Throws if the connection breaks mid-run. */
  messages: AsyncIterable<SseMessage>;
};

/**
 * Starts a triage run and returns once the server has accepted it. Aborting `signal` closes the
 * connection, which stops the run on the server.
 */
export async function openRunStream(
  body: RunRequest,
  signal: AbortSignal,
): Promise<RunStream> {
  let res: Response;
  try {
    res = await fetch(RUN_STREAM_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new RunError(null);
  }
  if (!res.ok || !res.body) throw new RunError(res.status);
  return {
    status: res.status,
    contentType: res.headers.get("content-type") ?? "",
    messages: readSse(res.body),
  };
}

const RUNS_PATH = "/api/runs";

/** The newest recorded runs, newest first. Throws `RunError` when the list cannot be read. */
export async function listRuns(signal: AbortSignal): Promise<RunRecord[]> {
  let res: Response;
  try {
    res = await fetch(RUNS_PATH, { signal });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new RunError(null);
  }
  if (!res.ok) throw new RunError(res.status);
  try {
    return parseRuns(await res.json());
  } catch (err) {
    if (signal.aborted) throw err;
    throw new RunError(res.status); // a 200 whose body is not JSON: not our backend
  }
}

export async function checkHealth(signal: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch("/api/health", { signal });
    return res.ok;
  } catch {
    return false;
  }
}
