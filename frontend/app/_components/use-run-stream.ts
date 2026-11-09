"use client";

import { useEffect, useReducer, useRef } from "react";
import { openRunStream, RUN_STREAM_PATH, RunError } from "@/lib/api";
import type { SseMessage } from "@/lib/sse";
import {
  isFailure,
  RUN_EVENTS,
  type RunRequest,
  runOutcome,
} from "@/lib/types";

export type Phase =
  | "idle"
  | "running"
  | "done"
  | "failed"
  | "lost"
  | "cancelled";
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
};

type Action =
  | { type: "start"; at: number }
  | { type: "line"; line: Omit<ConsoleLine, "id">; fromServer?: boolean }
  | { type: "end"; phase: Phase; at: number }
  | { type: "clear" };

const IDLE: State = {
  phase: "idle",
  lines: [],
  events: 0,
  nextId: 0,
  startedAt: null,
  endedAt: null,
};

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "start":
      return { ...IDLE, phase: "running", startedAt: action.at };
    case "line":
      return {
        ...state,
        lines: [...state.lines, { ...action.line, id: state.nextId }].slice(
          -MAX_LINES,
        ),
        events: state.events + (action.fromServer ? 1 : 0),
        nextId: state.nextId + 1,
      };
    case "end":
      return { ...state, phase: action.phase, endedAt: action.at };
    case "clear":
      return IDLE;
  }
}

function eventTone(message: SseMessage): Tone {
  if (isFailure(message)) return "bad";
  if (message.event === RUN_EVENTS.started) return "run";
  return message.event === RUN_EVENTS.completed ? "ok" : "muted";
}

/** Runs a triage over the event stream and records everything that comes back as console lines. */
export function useRunStream() {
  const [state, dispatch] = useReducer(reduce, IDLE);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function start(body: RunRequest) {
    const controller = new AbortController();
    abortRef.current = controller;
    const t0 = performance.now();
    const note = (text: string) => dispatch({ type: "line", line: { text } });
    const end = (phase: Phase) =>
      dispatch({ type: "end", phase, at: performance.now() });
    const lost = (text: string) => {
      dispatch({
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
        dispatch({
          type: "line",
          fromServer: true,
          line: {
            at: performance.now() - t0,
            label: message.event,
            tone: eventTone(message),
            text: message.data,
          },
        });
        outcome = runOutcome(message.event) ?? outcome;
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
        dispatch({
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
    start,
    cancel: () => abortRef.current?.abort(),
    clear: () => dispatch({ type: "clear" }),
  };
}
