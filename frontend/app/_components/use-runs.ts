"use client";

import { listRuns } from "@/lib/api";
import { useRunStatus } from "./run-stream";
import { useList } from "./use-list";

/**
 * The recorded runs, loaded when the page opens, again when this window's run changes phase or
 * gets its first event (the server records a run once it accepts it), once more a moment after a
 * cancel or a lost connection (the server records `aborted` only when it notices), and on
 * `refresh`. No polling.
 */
export function useRuns() {
  const { phase, started } = useRunStatus();
  return useList(
    listRuns,
    true,
    `${phase}:${started}`,
    phase === "cancelled" || phase === "lost",
  );
}
