// The dashboard's figures, from the run list (GET /v1/runs) and the detail of the newest run that
// found something (GET /v1/runs/{id}/detail). Pure, so the page only draws.

import type { ClusterDetail, RunOverview } from "./run-overview.ts";
import type { RunRecord, RunStatus } from "./types.ts";

const DAY_MS = 86_400_000;
const at = (iso: string) => new Date(iso).getTime();

/** The runs started in the `days` days before `now`. */
export const recent = (runs: RunRecord[], now: number, days = 7) =>
  runs.filter((r) => now - at(r.created_at) < days * DAY_MS);

/** A run that finished judging and clustering: it waits for review, or completed. */
const isAnalyzed = (r: RunRecord) =>
  r.status === "review_required" || r.status === "completed";

/** The tiles' figures: runs and failures of the last 7 days, and what waits for a review. */
export type RunStats = {
  runs: number;
  failures: number;
  awaiting: number;
  openProposals: number;
};

export function runStats(runs: RunRecord[], now: number): RunStats {
  const week = recent(runs, now);
  const waiting = runs.filter((r) => r.status === "review_required");
  return {
    runs: week.length,
    failures: week.reduce((sum, r) => sum + r.failed_traces, 0),
    awaiting: waiting.length,
    openProposals: waiting.reduce((sum, r) => sum + r.proposals, 0),
  };
}

/** The newest run that got as far as clustering: what the "what's breaking" panels describe. */
export function latestAnalyzed(runs: RunRecord[]): RunRecord | null {
  return runs.find((r) => isAnalyzed(r) && r.clusters > 0) ?? null;
}

/** Failed traces as a share of the traces the run judged; null when it judged none. */
export function failureRate({ summary }: RunOverview): number | null {
  return summary.traces > 0 ? summary.failed_traces / summary.traces : null;
}

export type CategoryShare = {
  /** A failure category, or `undiagnosed` for clusters with no diagnosis. */
  category: string;
  traces: number;
  clusters: number;
};

/** Failed traces by the category their cluster was diagnosed with, most first. */
export function categoryBreakdown(clusters: ClusterDetail[]): CategoryShare[] {
  const by = new Map<string, CategoryShare>();
  for (const c of clusters) {
    const category = c.diagnosis?.category ?? "undiagnosed";
    const share = by.get(category) ?? { category, traces: 0, clusters: 0 };
    share.traces += c.trace_ids.length;
    share.clusters += 1;
    by.set(category, share);
  }
  return [...by.values()].toSorted(
    (a, b) => b.traces - a.traces || a.category.localeCompare(b.category),
  );
}

/** The clusters holding the most failed traces, most first. */
export function largestClusters(
  clusters: ClusterDetail[],
  n: number,
): ClusterDetail[] {
  return clusters
    .toSorted((a, b) => b.trace_ids.length - a.trace_ids.length)
    .slice(0, n);
}

/** The newest `n` runs that finished judging (waiting or completed), oldest first, for a trend. */
export function failureTrend(runs: RunRecord[], n: number): RunRecord[] {
  return runs.filter(isAnalyzed).slice(0, n).reverse();
}

/** How many runs of the last 7 days ended in each status. */
export function outcomes(
  runs: RunRecord[],
  now: number,
): Record<RunStatus, number> {
  const counts: Record<RunStatus, number> = {
    in_progress: 0,
    review_required: 0,
    completed: 0,
    failed: 0,
    aborted: 0,
  };
  for (const r of recent(runs, now)) counts[r.status] += 1;
  return counts;
}

/** How long the oldest run awaiting review has waited (ms), or null when none waits. */
export function oldestWaiting(runs: RunRecord[], now: number): number | null {
  const waiting = runs.filter((r) => r.status === "review_required");
  if (waiting.length === 0) return null;
  return Math.max(...waiting.map((r) => now - at(r.ended_at ?? r.created_at)));
}
