"use client";

import { useEffect, useState } from "react";
import { getTrace, listTraces, RunError } from "@/lib/api";
import type { TraceDetail } from "@/lib/traces";
import { useList } from "./use-list";

/** The stored traces, loaded while `enabled`, again when `failedOnly` changes, and on `refresh`. */
export function useTraceList(enabled: boolean, failedOnly: boolean) {
  return useList(
    (signal) => listTraces(failedOnly, signal),
    enabled,
    failedOnly,
  );
}

export type TraceState =
  | { status: "loading" }
  | { status: "ready"; trace: TraceDetail }
  /** `missing`: the server has no whole trace by this id (404). */
  | { status: "error"; missing: boolean };

/** One trace, loaded once per id. Mount it with the id as `key`, so a new id starts clean. */
export function useTrace(traceId: string): TraceState {
  const [state, setState] = useState<TraceState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    getTrace(traceId, controller.signal).then(
      (trace) => setState({ status: "ready", trace }),
      (err) => {
        if (controller.signal.aborted) return;
        const missing = err instanceof RunError && err.status === 404;
        setState({ status: "error", missing });
      },
    );
    return () => controller.abort();
  }, [traceId]);

  return state;
}
