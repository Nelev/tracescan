"use client";

import { getRunOverview, getTrace, listRuns, listTraces } from "@/lib/api";
import { clusterIndex, INDEXED_RUNS, type Membership } from "@/lib/clusters";
import { isAnalyzed } from "@/lib/dashboard";
import type { TraceDetail } from "@/lib/traces";
import { usePage, useResource } from "./use-list";

/** One page of the stored traces, with how many there are in all, for the traces table. */
export function useTraceList(
  enabled: boolean,
  failedOnly: boolean,
  page: number,
  size: number,
) {
  return usePage(
    (signal) => listTraces(failedOnly, page, size, signal),
    enabled,
    `${failedOnly}:${page}:${size}`,
  );
}

// The traces read this session, by id. A stored trace is read only once it is whole and its
// spans never change, so a trace opened again (a cluster card reopened, the next exemplar and
// back, its full page) is not fetched again. Bounded: the oldest is dropped past the limit.
const MAX_CACHED = 50;
const cache = new Map<string, TraceDetail>();

function getTraceOnce(traceId: string, signal: AbortSignal) {
  const hit = cache.get(traceId);
  if (hit) return Promise.resolve(hit);
  return getTrace(traceId, signal).then((trace) => {
    cache.set(traceId, trace);
    if (cache.size > MAX_CACHED)
      cache.delete(cache.keys().next().value as string);
    return trace;
  });
}

/** One trace, loaded once per id. */
export function useTrace(traceId: string) {
  return useResource((signal) => getTraceOnce(traceId, signal), true, traceId);
}

/**
 * Which clusters each trace landed in, over the newest analyzed runs (`INDEXED_RUNS` run details,
 * read side by side; a run whose detail cannot be read is left out). Loaded once per page.
 */
export function useClusterIndex() {
  return useResource<Map<string, Membership[]>>(
    async (signal) => {
      const runs = (await listRuns(signal))
        .filter((r) => isAnalyzed(r) && r.clusters > 0)
        .slice(0, INDEXED_RUNS);
      const read = await Promise.allSettled(
        runs.map((r) => getRunOverview(r.run_id, signal)),
      );
      return clusterIndex(
        runs.flatMap((run, i) => {
          const result = read[i];
          return result.status === "fulfilled"
            ? [{ run, overview: result.value }]
            : [];
        }),
      );
    },
    true,
    "clusters",
  );
}
