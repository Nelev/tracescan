"use client";

import { listRuns, listRunsPage } from "@/lib/api";
import { useRunStatus } from "./run-stream";
import { useList, usePage } from "./use-list";

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

/**
 * One page of the recorded runs, with how many there are, reloaded on the same signals as
 * `useRuns` and whenever the page changes. A new run lands on page 1.
 */
export function useRunsPage(page: number, size: number) {
  const { phase, started } = useRunStatus();
  return usePage(
    (signal) => listRunsPage(page, size, signal),
    true,
    `${phase}:${started}:${page}:${size}`,
    phase === "cancelled" || phase === "lost",
  );
}
