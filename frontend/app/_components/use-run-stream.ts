"use client";

import { useEffect, useReducer, useRef } from "react";
import { openRunStream, RunError } from "@/lib/api";
import { outcomeOf, parseRunEvent, type RunEvent } from "@/lib/events";
import {
  type Ending,
  foldEvent,
  freezeView,
  INITIAL_VIEW,
  type RunView,
} from "@/lib/run-view";
import type { RunRequest } from "@/lib/types";

export type Phase = "idle" | "running" | Ending;

type State = {
  phase: Phase;
  /** Events received from the server, `ui_spec`s included. */
  events: number;
  /** Why the run did not start or was cut short, in words for the console; null otherwise. */
  error: string | null;
  /** `performance.now()` at the start and at the end of the run. */
  startedAt: number | null;
  endedAt: number | null;
  /** What the console draws and the progress view shows: a fold over the typed events. */
  view: RunView;
};

type Action =
  | { type: "start"; at: number }
  /** A message from the server, parsed, folded into the view. */
  | { type: "event"; event: RunEvent; at: number }
  | { type: "batch"; actions: Action[] }
  | { type: "end"; phase: Ending; at: number; error?: string }
  | { type: "clear" };

const IDLE: State = {
  phase: "idle",
  events: 0,
  error: null,
  startedAt: null,
  endedAt: null,
  view: INITIAL_VIEW,
};

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "start":
      return { ...IDLE, phase: "running", startedAt: action.at };
    case "event":
      return {
        ...state,
        events: state.events + 1,
        view: foldEvent(state.view, action.event, action.at),
      };
    case "batch":
      return action.actions.reduce(reduce, state);
    case "end":
      return {
        ...state,
        phase: action.phase,
        endedAt: action.at,
        error: action.error ?? null,
        view: freezeView(state.view, action.phase),
      };
    case "clear":
      return IDLE;
  }
}

/**
 * Collects actions and applies them together once per animation frame, so a burst of parallel
 * cluster events is one render, not one per event. `flush` applies what is queued at once; the
 * run's last actions use it so the end never overtakes the events before it.
 */
function createBatcher(dispatch: (action: Action) => void) {
  const queue: Action[] = [];
  let frame: number | null = null;

  function flush() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    if (queue.length > 0) dispatch({ type: "batch", actions: queue.splice(0) });
  }

  return {
    push(action: Action) {
      queue.push(action);
      frame ??= requestAnimationFrame(flush);
    },
    flush,
  };
}

/** Runs a triage over the event stream and folds what comes back into the run view. */
export function useRunStream() {
  const [state, dispatch] = useReducer(reduce, IDLE);
  const abortRef = useRef<AbortController | null>(null);

  // Aborting ends the run through the catch below, which flushes the batch.
  useEffect(() => () => abortRef.current?.abort(), []);

  async function start(body: RunRequest) {
    const controller = new AbortController();
    abortRef.current = controller;
    const batch = createBatcher(dispatch);
    const t0 = performance.now();
    const end = (phase: Ending, error?: string) => {
      batch.push({ type: "end", phase, at: performance.now(), error });
      batch.flush();
    };

    dispatch({ type: "start", at: t0 });

    try {
      const stream = await openRunStream(body, controller.signal);

      let outcome: "done" | "failed" | null = null;
      for await (const message of stream.messages) {
        const event = parseRunEvent(message);
        batch.push({ type: "event", event, at: performance.now() - t0 });
        outcome = outcomeOf(event) ?? outcome;
      }
      if (outcome === null) {
        end("lost", "The stream ended before run_completed or run_failed.");
      } else {
        end(outcome);
      }
    } catch (err) {
      if (controller.signal.aborted) {
        end("cancelled");
      } else if (err instanceof RunError) {
        // Only openRunStream throws RunError, so the run never started.
        end(
          "failed",
          err.status === null
            ? "Could not reach the backend: check that it is running."
            : `The run did not start (HTTP ${err.status}): check that the backend is running, then its log.`,
        );
      } else {
        end("lost", "The connection was interrupted.");
      }
    }
  }

  return {
    phase: state.phase,
    events: state.events,
    error: state.error,
    startedAt: state.startedAt,
    endedAt: state.endedAt,
    view: state.view,
    start,
    cancel: () => abortRef.current?.abort(),
    clear: () => dispatch({ type: "clear" }),
  };
}
