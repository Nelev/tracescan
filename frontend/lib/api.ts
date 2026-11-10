import {
  type Decisions,
  parseReviewResult,
  parseRunDetail,
  type ReviewResult,
  type RunDetail,
} from "./review";
import { parseRuns } from "./runs";
import { readSse, type SseMessage } from "./sse";
import type { RunRecord, RunRequest } from "./types";

/**
 * A request the backend did not answer as expected. `status` is null when it could not be reached
 * at all. `unreadable`: it answered a 2xx, but not with what our backend sends, so whatever the
 * request asked for may well have been done.
 */
export class RunError extends Error {
  constructor(
    readonly status: number | null,
    readonly unreadable = false,
  ) {
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
const runPath = (runId: string) => `${RUNS_PATH}/${encodeURIComponent(runId)}`;

/**
 * A JSON answer of the backend, read by `parse`, which returns null for a body that is off
 * contract. Throws `RunError`: for a status that is not a 2xx, and as `unreadable` for a 2xx
 * whose body is not JSON or off contract.
 */
async function fetchJson<T>(
  path: string,
  init: RequestInit,
  parse: (body: unknown) => T | null,
): Promise<T> {
  const aborted = () => init.signal?.aborted ?? false;
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (err) {
    if (aborted()) throw err;
    throw new RunError(null);
  }
  if (!res.ok) throw new RunError(res.status);
  let body: unknown;
  try {
    body = await res.json();
  } catch (err) {
    if (aborted()) throw err;
    throw new RunError(res.status, true); // not JSON: not our backend
  }
  const parsed = parse(body);
  if (parsed === null) throw new RunError(res.status, true);
  return parsed;
}

/** The newest recorded runs, newest first. Throws `RunError` when the list cannot be read. */
export function listRuns(signal: AbortSignal): Promise<RunRecord[]> {
  return fetchJson(RUNS_PATH, { signal }, parseRuns);
}

/** A run's status and proposals. Throws `RunError`: 404 for a run the server does not know. */
export function getRun(runId: string, signal: AbortSignal): Promise<RunDetail> {
  return fetchJson(runPath(runId), { signal }, parseRunDetail);
}

/**
 * Sends the review of a run that waits for one: a decision for every proposal. The server
 * resumes the run and answers when its actions are applied. Throws `RunError`: 409 when the run
 * is not waiting, 422 when the decisions do not match its proposals, 502 when the resume failed,
 * and `unreadable` when the review was taken but its answer could not be read.
 */
export function reviewRun(
  runId: string,
  decisions: Decisions,
): Promise<ReviewResult> {
  return fetchJson(
    `${runPath(runId)}/review`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decisions }),
    },
    parseReviewResult,
  );
}

export async function checkHealth(signal: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch("/api/health", { signal });
    return res.ok;
  } catch {
    return false;
  }
}
