"use client";

import { useEffect, useState } from "react";
import { getRun, RunError, reviewRun } from "@/lib/api";
import {
  type Decisions,
  type Failure,
  loadProblem,
  type ReviewResult,
  type RunDetail,
  submitProblem,
} from "@/lib/review";
import type { Decision } from "@/lib/types";

/**
 * Where the review of one run stands. `open` is a run that was loaded, whether or not it still
 * waits (its `detail.status` says); `problem` there is why the last send was not taken.
 */
export type ReviewState =
  | { step: "loading" }
  | { step: "unavailable"; problem: string }
  | {
      step: "open";
      detail: RunDetail;
      sending: boolean;
      problem: string | null;
    }
  | { step: "reviewed"; detail: RunDetail; result: ReviewResult };

const NOT_REACHED: Failure = { status: null, unreadable: false };
const failureOf = (err: unknown): Failure =>
  err instanceof RunError ? err : NOT_REACHED;

/**
 * Loads a run for review, keeps the reviewer's decisions, and sends them. Mount it with the run
 * id as `key`: one instance reviews one run. `onReviewed` is called once the server has taken
 * the review.
 */
export function useReview(runId: string, onReviewed: (runId: string) => void) {
  const [state, setState] = useState<ReviewState>({ step: "loading" });
  const [decisions, setDecisions] = useState<Decisions>({});
  const [loads, setLoads] = useState(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: loads is not read, it is the signal to load again
  useEffect(() => {
    const controller = new AbortController();
    getRun(runId, controller.signal).then(
      (detail) =>
        setState({ step: "open", detail, sending: false, problem: null }),
      (err) => {
        if (!controller.signal.aborted) {
          setState({
            step: "unavailable",
            problem: loadProblem(failureOf(err)),
          });
        }
      },
    );
    return () => controller.abort();
  }, [runId, loads]);

  async function submit() {
    if (state.step !== "open" || state.sending) return;
    const { detail } = state;
    setState({ step: "open", detail, sending: true, problem: null });
    try {
      const result = await reviewRun(runId, decisions);
      setState({ step: "reviewed", detail, result });
      onReviewed(runId);
    } catch (err) {
      const failure = failureOf(err);
      const problem = submitProblem(failure);
      if (failure.unreadable) {
        // The server answered a 2xx, so it took the review: nothing to send again. Loading the
        // run again shows where it stands.
        setState({ step: "unavailable", problem });
        onReviewed(runId);
      } else {
        // Not taken: the decisions are kept, so the reviewer can send them again.
        setState({ step: "open", detail, sending: false, problem });
      }
    }
  }

  return {
    state,
    decisions,
    decide: (clusterId: string, decision: Decision) =>
      setDecisions((made) => ({ ...made, [clusterId]: decision })),
    submit,
    /** Loads the run again and forgets the decisions: its proposals may have changed. */
    reload: () => {
      setState({ step: "loading" });
      setDecisions({});
      setLoads((n) => n + 1);
    },
  };
}
