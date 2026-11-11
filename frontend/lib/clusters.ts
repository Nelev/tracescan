// Which clusters each trace landed in. A cluster lives in its run's checkpoint, and the run detail
// lists each cluster's trace ids, so the index is built from the details of the newest analyzed
// runs: no endpoint maps a trace to its clusters.

import type { RunOverview } from "./run-overview.ts";
import type { RunRecord } from "./types.ts";

/** One cluster a trace is in: the run, the cluster, and what the diagnosis called it. */
export type Membership = {
  runId: string;
  createdAt: string;
  clusterId: string;
  signature: string;
  /** The diagnosed category; null for a cluster with no diagnosis. */
  category: string | null;
};

/** How many of the newest analyzed runs the index reads (one run detail each). */
export const INDEXED_RUNS = 5;

/**
 * Each trace's memberships, newest run first, from runs given newest first. A trace a run did not
 * cluster has no entry for it.
 */
export function clusterIndex(
  runs: { run: RunRecord; overview: RunOverview }[],
): Map<string, Membership[]> {
  const index = new Map<string, Membership[]>();
  for (const { run, overview } of runs) {
    for (const c of overview.clusters) {
      const membership: Membership = {
        runId: run.run_id,
        createdAt: run.created_at,
        clusterId: c.cluster_id,
        signature: c.signature,
        category: c.diagnosis?.category ?? null,
      };
      for (const traceId of c.trace_ids) {
        const list = index.get(traceId);
        if (list) list.push(membership);
        else index.set(traceId, [membership]);
      }
    }
  }
  return index;
}
