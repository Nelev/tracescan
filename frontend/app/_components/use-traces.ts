"use client";

import { getTrace, listTraces } from "@/lib/api";
import type { TraceDetail } from "@/lib/traces";
import { useList, useResource } from "./use-list";

/** The stored traces, loaded while `enabled`, again when `failedOnly` changes, and on `refresh`. */
export function useTraceList(enabled: boolean, failedOnly: boolean) {
  return useList(
    (signal) => listTraces(failedOnly, signal),
    enabled,
    failedOnly,
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
