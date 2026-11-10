"use client";

import { useEffect, useState } from "react";
import { listRuns } from "@/lib/api";
import type { RunRecord } from "@/lib/types";

export type RunsState = {
  /** `error`: the last load failed; `runs` still holds what an earlier load returned. */
  status: "loading" | "ready" | "error";
  runs: RunRecord[];
  /** When `runs` was loaded (epoch ms); null before the first load. */
  loadedAt: number | null;
};

const RECHECK_MS = 1500;

/**
 * The recorded runs, loaded while `enabled` and again whenever `reloadOn` changes or `refresh`
 * is called. A load that is overtaken by the next one is aborted, so the list never goes back.
 *
 * `recheck` loads once more a moment later, for a change the server records late: it marks a run
 * as aborted only when it notices that the connection closed.
 */
export function useRuns(enabled: boolean, reloadOn: unknown, recheck = false) {
  const [state, setState] = useState<RunsState>({
    status: "loading",
    runs: [],
    loadedAt: null,
  });
  const [refreshes, setRefreshes] = useState(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reloadOn and refreshes are not read, they are the signals to load again
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const load = () => {
      setState((s) => ({ ...s, status: "loading" }));
      listRuns(controller.signal).then(
        (runs) => setState({ status: "ready", runs, loadedAt: Date.now() }),
        () => {
          if (!controller.signal.aborted) {
            setState((s) => ({ ...s, status: "error" }));
          }
        },
      );
    };
    load();
    const again = recheck ? setTimeout(load, RECHECK_MS) : undefined;
    return () => {
      clearTimeout(again);
      controller.abort();
    };
  }, [enabled, reloadOn, refreshes, recheck]);

  return { ...state, refresh: () => setRefreshes((n) => n + 1) };
}
