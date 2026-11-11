"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  type ReactNode,
  use,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { runPath } from "@/lib/runs";
import { useRunStream } from "./use-run-stream";

export type RunStream = ReturnType<typeof useRunStream>;

/**
 * Where this window's run stands, without what it streams: what the nav, the New run form and the
 * run lists read. It changes when the run starts, is named, ends or fails, not on every batch of
 * events, so they do not re-render while a run streams.
 */
export type RunStatus = Pick<
  RunStream,
  "runId" | "phase" | "error" | "start" | "cancel"
> & {
  /** The server sent its first event: it has recorded the run. */
  started: boolean;
};

const RunStreamContext = createContext<RunStream | null>(null);
const RunStatusContext = createContext<RunStatus | null>(null);

/**
 * The run this window started, held above the pages so it keeps streaming while the reader moves
 * between them. Once the server names the run, the window opens its page.
 */
export function RunStreamProvider({ children }: { children: ReactNode }) {
  const run = useRunStream();
  const router = useRouter();
  const opened = useRef<string | null>(null);
  const { runId, phase, error, start, cancel } = run;
  const started = run.events > 0;
  const status = useMemo<RunStatus>(
    () => ({ runId, phase, error, start, cancel, started }),
    [runId, phase, error, start, cancel, started],
  );

  useEffect(() => {
    if (runId !== null && runId !== opened.current) {
      opened.current = runId;
      router.push(runPath(runId));
    }
  }, [runId, router]);

  return (
    <RunStatusContext value={status}>
      <RunStreamContext value={run}>{children}</RunStreamContext>
    </RunStatusContext>
  );
}

/** The run this window started, with everything it streamed: for the pages that show it. */
export function useRun(): RunStream {
  const run = use(RunStreamContext);
  if (run === null) throw new Error("useRun outside RunStreamProvider");
  return run;
}

/** Where this window's run stands, re-rendering only when that changes. */
export function useRunStatus(): RunStatus {
  const status = use(RunStatusContext);
  if (status === null)
    throw new Error("useRunStatus outside RunStreamProvider");
  return status;
}
