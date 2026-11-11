// The run list of GET /v1/runs: read once into typed rows, and the words the Runs tab shows.

import type { RunRecord, RunStatus } from "./types.ts";

/**
 * What a status means, whatever it is the status of: nothing (`neutral`), under way (`info`),
 * waiting for a person (`warning`), ended well, ended badly, cut short by choice (`stopped`).
 */
export type StatusTone =
  | "neutral"
  | "info"
  | "warning"
  | "success"
  | "destructive"
  | "stopped";

/** How each status reads in the list. Only a run that waits for its review is a `warning`. */
export const RUN_STATUS: Record<
  RunStatus,
  { label: string; tone: StatusTone }
> = {
  in_progress: { label: "In progress", tone: "info" },
  review_required: { label: "Awaiting review", tone: "warning" },
  completed: { label: "Completed", tone: "success" },
  failed: { label: "Failed", tone: "destructive" },
  aborted: { label: "Aborted", tone: "stopped" }, // stopped by its reader, not a failure
};

export const isText = (v: unknown): v is string => typeof v === "string";
export const isRunStatus = (v: unknown): v is RunStatus =>
  isText(v) && Object.hasOwn(RUN_STATUS, v);
export const isTextOrNull = (v: unknown): v is string | null =>
  v === null || isText(v);
export const isCount = (v: unknown): v is number => Number.isInteger(v);

/** "1 run", "3 runs": a count with its noun. */
export const plural = (n: number, one: string, many = `${one}s`) =>
  `${n} ${n === 1 ? one : many}`;

function isRun(row: unknown): row is RunRecord {
  if (typeof row !== "object" || row === null) return false;
  const r = row as Record<string, unknown>;
  return (
    isText(r.run_id) &&
    isText(r.target_app) &&
    isTextOrNull(r.since) &&
    isTextOrNull(r.until) &&
    isRunStatus(r.status) &&
    isTextOrNull(r.started_by) &&
    isText(r.created_at) &&
    isTextOrNull(r.ended_at) &&
    isCount(r.failed_traces) &&
    isCount(r.clusters) &&
    isCount(r.proposals)
  );
}

/** The rows of a response body that are on contract; anything else is left out, never thrown. */
export function parseRuns(body: unknown): RunRecord[] {
  return Array.isArray(body) ? body.filter(isRun) : [];
}

/** Enough of a run id to tell runs apart in a list. */
export function shortId(runId: string): string {
  return runId.slice(0, 8);
}

const WHEN: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
};
// The reader's own locale and time zone: built once, not once per table cell.
let readersFormat: Intl.DateTimeFormat | undefined;

/**
 * A timestamp as "10 Nov, 14:32". `locale` and `timeZone` default to the reader's own; the tests
 * pass both.
 */
export function formatWhen(
  iso: string,
  locale?: string,
  timeZone?: string,
): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  if (locale === undefined && timeZone === undefined) {
    readersFormat ??= new Intl.DateTimeFormat(undefined, WHEN);
    return readersFormat.format(date);
  }
  return new Intl.DateTimeFormat(locale, { ...WHEN, timeZone }).format(date);
}

/** The time window a run looked at, `since` inclusive and `until` exclusive. */
export function formatWindow(
  since: string | null,
  until: string | null,
  when: (iso: string) => string = formatWhen,
): string {
  if (since === null && until === null) return "All time";
  if (until === null) return `From ${when(since as string)}`;
  if (since === null) return `Until ${when(until)}`;
  return `${when(since)} → ${when(until)}`;
}
