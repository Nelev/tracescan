"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import {
  openRunStream,
  RUN_STREAM_PATH,
  RunError,
  resumeStreamPath,
} from "@/lib/api";
import {
  foldEvent,
  isFailure,
  type Outcome,
  outcomeOf,
  parseRunEvent,
  type RunEvent,
  type UiMessage,
} from "@/lib/events";
import { foldProgress, type LiveProgress, NO_PROGRESS } from "@/lib/progress";
import { startProblem } from "@/lib/review";
import type { SseMessage } from "@/lib/sse";
import { RUN_EVENTS, type RunRequest } from "@/lib/types";

/** How a run's stream ended. `review`: the run stopped at the human review and waits for it. */
type Ending = Outcome | "lost" | "cancelled";
export type Phase = "idle" | "running" | Ending;
export type Tone = "muted" | "run" | "ok" | "bad";

export type ConsoleLine = {
  id: number;
  /** Milliseconds since the run started. A line with neither `at` nor `label` is a console note. */
  at?: number;
  label?: string;
  /** Colors the label. */
  tone?: Tone;
  text: string;
};

// The raw log keeps the last lines only, so a long run cannot grow the page without bound.
const MAX_LINES = 500;

type State = {
  phase: Phase;
  /** The run's id, from `run_started`: what its review is sent under. Null before it. */
  runId: string | null;
  /** Every message as received, for the raw log. */
  lines: ConsoleLine[];
  /** Events received from the server; `lines` may have dropped the oldest. */
  events: number;
  nextId: number;
  /** Why the run did not start or was cut short, in words for the console; null otherwise. */
  error: string | null;
  /** `performance.now()` at the start and at the end of the run. */
  startedAt: number | null;
  endedAt: number | null;
  /** What the console draws: the UI spec the server sent for each message (lib/events.ts). */
  messages: UiMessage[];
  /** Where the run stands, from its progress events: drives the run page's stepper. */
  live: LiveProgress;
  /**
   * This run was reviewed. The graph pauses at the review before the stream closes (the server
   * still sends the proposals and their UI specs), so a review can be taken while it is open; its
   * end then must not set the run back to waiting.
   */
  reviewed: boolean;
};

type Action =
  | { type: "start"; at: number }
  /** A note the raw log prints on its own. */
  | { type: "line"; line: Omit<ConsoleLine, "id"> }
  /** A message from the server: a raw line, and its parsed event folded into the messages. */
  | { type: "event"; message: SseMessage; event: RunEvent; at: number }
  | { type: "batch"; actions: Action[] }
  | { type: "end"; phase: Ending; at: number; error?: string }
  /** The run was reviewed: if it is this page's run, it no longer waits. */
  | { type: "reviewed"; runId: string };

const IDLE: State = {
  phase: "idle",
  runId: null,
  lines: [],
  events: 0,
  nextId: 0,
  error: null,
  startedAt: null,
  endedAt: null,
  messages: [],
  live: NO_PROGRESS,
  reviewed: false,
};

function eventTone(event: RunEvent): Tone {
  if (isFailure(event)) return "bad";
  if (event.kind === "started") return "run";
  return event.kind === "completed" || event.kind === "review" ? "ok" : "muted";
}

function appendLine(state: State, line: Omit<ConsoleLine, "id">): State {
  return {
    ...state,
    lines: [...state.lines, { ...line, id: state.nextId }].slice(-MAX_LINES),
    nextId: state.nextId + 1,
  };
}

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "start":
      return { ...IDLE, phase: "running", startedAt: action.at };
    case "line":
      return appendLine(state, action.line);
    case "event":
      return {
        ...appendLine(state, {
          at: action.at,
          label: action.message.event,
          tone: eventTone(action.event),
          text: action.message.data,
        }),
        events: state.events + 1,
        messages: foldEvent(state.messages, action.event),
        live:
          action.event.kind === "progress"
            ? foldProgress(state.live, action.event.progress)
            : state.live,
        runId:
          action.event.kind === "started" ? action.event.runId : state.runId,
      };
    case "reviewed":
      // The review ended the run, whether the stream had closed at the review or was still
      // sending the proposals' specs.
      if (state.runId !== action.runId) return state;
      return {
        ...state,
        reviewed: true,
        phase: state.phase === "review" ? "done" : state.phase,
      };
    case "batch":
      return action.actions.reduce(reduce, state);
    case "end":
      return {
        ...state,
        phase:
          state.reviewed && action.phase === "review" ? "done" : action.phase,
        endedAt: action.at,
        error: action.error ?? null,
      };
  }
}

/**
 * Collects actions and applies them together once per animation frame, so a burst of events is
 * one render, not one per event. `flush` applies what is queued at once; the run's last actions
 * use it so the end never overtakes the events before it.
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

/**
 * Runs a triage over the event stream, records everything that comes back as raw lines, and folds
 * the UI specs into the messages the console draws.
 */
export function useRunStream() {
  const [state, dispatch] = useReducer(reduce, IDLE);
  const abortRef = useRef<AbortController | null>(null);

  // Aborting ends the run through the catch below, which flushes the batch.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Stable for the hook's life (they read only the dispatcher and a ref), so the provider's
  // run-status context changes only when the status does.
  const open = useCallback(async (body: RunRequest | null, path: string) => {
    abortRef.current?.abort(); // one stream per window: a new one replaces the last
    const controller = new AbortController();
    abortRef.current = controller;
    // A replaced stream still ends (its catch sees the abort) after the new one has started:
    // from then on it must not dispatch, or it would end the new run as cancelled.
    const batch = createBatcher((action) => {
      if (abortRef.current === controller) dispatch(action);
    });
    const t0 = performance.now();
    const note = (text: string) => batch.push({ type: "line", line: { text } });
    const end = (phase: Ending, error?: string) => {
      batch.push({ type: "end", phase, at: performance.now(), error });
      batch.flush();
    };
    // A run that did not start or was cut short: one raw line, and the same words, as a sentence,
    // above the console's messages.
    const stop = (phase: Ending, label: string, text: string, at?: number) => {
      batch.push({ type: "line", line: { at, label, tone: "bad", text } });
      end(phase, `${text[0].toUpperCase()}${text.slice(1)}.`);
    };
    const lost = (text: string) =>
      stop("lost", "connection lost", text, performance.now() - t0);

    dispatch({ type: "start", at: t0 });
    note(`POST ${path}${body === null ? "" : `  ${JSON.stringify(body)}`}`);

    try {
      const stream = await openRunStream(path, body, controller.signal);
      note(`${stream.status} ${stream.contentType.split(";")[0]}`);

      let outcome: Outcome | null = null;
      for await (const message of stream.messages) {
        const event = parseRunEvent(message);
        batch.push({
          type: "event",
          message,
          event,
          at: performance.now() - t0,
        });
        outcome = outcomeOf(event) ?? outcome;
      }
      if (outcome === null) {
        lost(
          `the stream ended before ${RUN_EVENTS.reviewRequired}, ${RUN_EVENTS.completed} or ${RUN_EVENTS.failed}`,
        );
      } else {
        note("stream closed");
        end(outcome);
      }
    } catch (err) {
      if (controller.signal.aborted) {
        note("cancelled");
        end("cancelled");
      } else if (err instanceof RunError) {
        // Only openRunStream throws RunError, so the run never started.
        const problem = startProblem(err);
        batch.push({
          type: "line",
          line: { label: "error", tone: "bad", text: problem },
        });
        end("failed", problem);
      } else {
        lost("the connection was interrupted");
      }
    }
  }, []);

  /** Start a new run. */
  const start = useCallback(
    (body: RunRequest) => open(body, RUN_STREAM_PATH),
    [open],
  );
  /** Go on with a run that failed or was aborted, from its last checkpoint. */
  const resume = useCallback(
    (runId: string) => open(null, resumeStreamPath(runId)),
    [open],
  );
  const cancel = useCallback(() => abortRef.current?.abort(), []);
  const markReviewed = useCallback(
    (runId: string) => dispatch({ type: "reviewed", runId }),
    [],
  );

  return {
    phase: state.phase,
    runId: state.runId,
    lines: state.lines,
    events: state.events,
    error: state.error,
    startedAt: state.startedAt,
    endedAt: state.endedAt,
    messages: state.messages,
    live: state.live,
    start,
    resume,
    cancel,
    markReviewed,
  };
}
