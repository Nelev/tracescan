"use client";

import { useEffect, useReducer, useRef } from "react";
import { openRunStream, RUN_STREAM_PATH, RunError } from "@/lib/api";
import {
  isFailure,
  outcomeOf,
  parseRunEvent,
  type RunEvent,
} from "@/lib/events";
import {
  type Ending,
  foldEvent,
  freezeView,
  INITIAL_VIEW,
  type RunView,
} from "@/lib/run-view";
import type { SseMessage } from "@/lib/sse";
import type { RunRequest } from "@/lib/types";

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

// The console keeps the last lines only, so a long run cannot grow the page without bound.
const MAX_LINES = 500;

type State = {
  phase: Phase;
  lines: ConsoleLine[];
  /** Events received from the server; `lines` may have dropped the oldest. */
  events: number;
  nextId: number;
  /** `performance.now()` at the start and at the end of the run. */
  startedAt: number | null;
  endedAt: number | null;
  /** The progress view: a fold over the typed events (lib/run-view.ts). */
  view: RunView;
};

type Action =
  | { type: "start"; at: number }
  /** A note the console prints on its own. */
  | { type: "line"; line: Omit<ConsoleLine, "id"> }
  /** A message from the server: a console line, and its parsed event folded into the view. */
  | { type: "event"; message: SseMessage; event: RunEvent; at: number }
  | { type: "batch"; actions: Action[] }
  | { type: "end"; phase: Ending; at: number }
  | { type: "clear" };

const IDLE: State = {
  phase: "idle",
  lines: [],
  events: 0,
  nextId: 0,
  startedAt: null,
  endedAt: null,
  view: INITIAL_VIEW,
};

function eventTone(event: RunEvent): Tone {
  if (isFailure(event)) return "bad";
  if (event.kind === "started") return "run";
  return event.kind === "completed" ? "ok" : "muted";
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
        view: foldEvent(state.view, action.event, action.at),
      };
    case "batch":
      return action.actions.reduce(reduce, state);
    case "end":
      return {
        ...state,
        phase: action.phase,
        endedAt: action.at,
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

/** Runs a triage over the event stream and records everything that comes back as console lines. */
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
    const note = (text: string) => batch.push({ type: "line", line: { text } });
    const end = (phase: Ending) => {
      batch.push({ type: "end", phase, at: performance.now() });
      batch.flush();
    };
    const lost = (text: string) => {
      batch.push({
        type: "line",
        line: {
          at: performance.now() - t0,
          label: "connection lost",
          tone: "bad",
          text,
        },
      });
      end("lost");
    };

    dispatch({ type: "start", at: t0 });
    note(`POST ${RUN_STREAM_PATH}  ${JSON.stringify(body)}`);

    try {
      const stream = await openRunStream(body, controller.signal);
      note(`${stream.status} ${stream.contentType.split(";")[0]}`);

      let outcome: "done" | "failed" | null = null;
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
        lost("the stream ended before run_completed or run_failed");
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
        batch.push({
          type: "line",
          line: {
            label: "error",
            tone: "bad",
            text:
              err.status === null
                ? "could not reach the backend: check that it is running"
                : `the run did not start (HTTP ${err.status}): check that the backend is running, then its log`,
          },
        });
        end("failed");
      } else {
        lost("the connection was interrupted");
      }
    }
  }

  return {
    phase: state.phase,
    lines: state.lines,
    events: state.events,
    startedAt: state.startedAt,
    endedAt: state.endedAt,
    view: state.view,
    start,
    cancel: () => abortRef.current?.abort(),
    clear: () => dispatch({ type: "clear" }),
  };
}
