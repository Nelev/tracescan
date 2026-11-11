"use client";

import { listRuns } from "@/lib/api";
import type { RunRecord } from "@/lib/types";
import { type ListState, useList } from "./use-list";

export type RunsState = ListState<RunRecord>;

/**
 * The recorded runs, loaded while `enabled` and again whenever `reloadOn` changes or `refresh`
 * is called. `recheck` loads once more a moment later, for a change the server records late: it
 * marks a run as aborted only when it notices that the connection closed.
 */
export function useRuns(enabled: boolean, reloadOn: unknown, recheck = false) {
  return useList(listRuns, enabled, reloadOn, recheck);
}
