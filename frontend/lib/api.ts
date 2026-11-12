import { type Page, pageOffset, totalFrom } from "./pages";
import {
  type Decisions,
  parseReviewResult,
  parseRunDetail,
  type ReviewResult,
  type RunDetail,
  retryAfterSeconds,
} from "./review";
import { parseRunOverview, type RunOverview } from "./run-overview";
import { parseRuns } from "./runs";
import { withSessionToken } from "./session-token";
import { readSse, type SseMessage } from "./sse";
import {
  parseTraceDetail,
  parseTraces,
  type TraceDetail,
  type TraceRow,
} from "./traces";
import type { RunRecord, RunRequest } from "./types";

/**
 * A request the backend did not answer as expected. `status` is null when it could not be reached
 * at all. `unreadable`: it answered a 2xx, but not with what our backend sends, so whatever the
 * request asked for may well have been done. `retryAfterS`: the wait a 429 named, in seconds.
 */
export class RunError extends Error {
  readonly unreadable: boolean;
  readonly retryAfterS: number | null;

  constructor(
    readonly status: number | null,
    { unreadable = false, retryAfterS = null as number | null } = {},
  ) {
    super(status === null ? "unreachable" : `http ${status}`);
    this.unreadable = unreadable;
    this.retryAfterS = retryAfterS;
  }

  /** A response the backend refused: its status, and the wait it named if it gave one. */
  static refused(res: Response): RunError {
    return new RunError(res.status, {
      retryAfterS: retryAfterSeconds(res.headers.get("retry-after")),
    });
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
    res = await fetch(
      RUN_STREAM_PATH,
      await withSessionToken({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      }),
    );
  } catch (err) {
    if (signal.aborted) throw err;
    throw new RunError(null);
  }
  if (!res.ok || !res.body) throw RunError.refused(res);
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
  return (await fetchParsed(path, init, parse)).value;
}

/**
 * One page of a list: the rows the body holds, and the whole list's total from the server's
 * `X-Total-Count` header (a server without it sent everything it has, so the rows are the total).
 */
async function fetchPage<T>(
  path: string,
  init: RequestInit,
  parse: (body: unknown) => T[] | null,
): Promise<Page<T>> {
  const { value, headers } = await fetchParsed(path, init, parse);
  return {
    items: value,
    total: totalFrom(headers.get(TOTAL_COUNT), value.length),
  };
}

const TOTAL_COUNT = "X-Total-Count";

async function fetchParsed<T>(
  path: string,
  init: RequestInit,
  parse: (body: unknown) => T | null,
): Promise<{ value: T; headers: Headers }> {
  const aborted = () => init.signal?.aborted ?? false;
  let res: Response;
  try {
    res = await fetch(path, await withSessionToken(init));
  } catch (err) {
    if (aborted()) throw err;
    throw new RunError(null);
  }
  if (!res.ok) throw RunError.refused(res);
  let body: unknown;
  try {
    body = await res.json();
  } catch (err) {
    if (aborted()) throw err;
    throw new RunError(res.status, { unreadable: true }); // not JSON: not our backend
  }
  const parsed = parse(body);
  if (parsed === null) throw new RunError(res.status, { unreadable: true });
  return { value: parsed, headers: res.headers };
}

/** The newest recorded runs, newest first. Throws `RunError` when the list cannot be read. */
export function listRuns(signal: AbortSignal): Promise<RunRecord[]> {
  return fetchJson(RUNS_PATH, { signal }, parseRuns);
}

/** One page of the recorded runs, newest first, with how many there are in all. */
export function listRunsPage(
  page: number,
  size: number,
  signal: AbortSignal,
): Promise<Page<RunRecord>> {
  const query = new URLSearchParams({
    limit: String(size),
    offset: String(pageOffset(page, size)),
  });
  return fetchPage(`${RUNS_PATH}?${query}`, { signal }, parseRuns);
}

/** A run's status and proposals. Throws `RunError`: 404 for a run the server does not know. */
export function getRun(runId: string, signal: AbortSignal): Promise<RunDetail> {
  return fetchJson(runPath(runId), { signal }, parseRunDetail);
}

/** What a run found, cluster by cluster. Throws `RunError`: 404 for a run the server does not know. */
export function getRunOverview(
  runId: string,
  signal: AbortSignal,
): Promise<RunOverview> {
  return fetchJson(`${runPath(runId)}/detail`, { signal }, parseRunOverview);
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

const TRACES_PATH = "/api/traces";

/**
 * One page of the stored traces, newest first, failed or not (only failed ones with
 * `failedOnly`), with how many there are in all. Throws `RunError` when the list cannot be read.
 */
export function listTraces(
  failedOnly: boolean,
  page: number,
  size: number,
  signal: AbortSignal,
): Promise<Page<TraceRow>> {
  const query = new URLSearchParams({
    limit: String(size),
    offset: String(pageOffset(page, size)),
  });
  if (failedOnly) query.set("failed_only", "true");
  return fetchPage(`${TRACES_PATH}?${query}`, { signal }, parseTraces);
}

/**
 * One trace: its span tree, already sanitized by the server, and its scores. Throws `RunError`:
 * 404 for a trace the server does not have whole.
 */
export function getTrace(
  traceId: string,
  signal: AbortSignal,
): Promise<TraceDetail> {
  return fetchJson(
    `${TRACES_PATH}/${encodeURIComponent(traceId)}`,
    { signal },
    parseTraceDetail,
  );
}

/** Whether the backend is up: the one call that goes without a session token. */
export async function checkHealth(signal: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch("/api/health", { signal });
    return res.ok;
  } catch {
    return false;
  }
}
