"use client";

import { getTrace, listTraces } from "@/lib/api";
import { useList, useResource } from "./use-list";

/** The stored traces, loaded while `enabled`, again when `failedOnly` changes, and on `refresh`. */
export function useTraceList(enabled: boolean, failedOnly: boolean) {
  return useList(
    (signal) => listTraces(failedOnly, signal),
    enabled,
    failedOnly,
  );
}

/** One trace, loaded once per id. */
export function useTrace(traceId: string) {
  return useResource((signal) => getTrace(traceId, signal), true, traceId);
}
