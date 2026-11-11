import { isRecord } from "./guards.ts";
import { type ProgressData, parseProgress } from "./progress.ts";
import type { SseMessage } from "./sse.ts";
import { RUN_EVENTS } from "./types.ts";

/**
 * One stream message, parsed once at the edge. Anything that does not match the contract becomes
 * `unknown`: the raw log still prints it, and the console draws nothing for it. A progress event
 * carries its parsed data (lib/progress.ts), which drives the run page's stepper and tints a
 * failed step's line in the raw log. `run_started`
 * names the run, which is how its review is sent later; null when the id is missing.
 */
export type RunEvent =
  | { kind: "started"; runId: string | null }
  | { kind: "progress"; progress: ProgressData }
  | { kind: "review" }
  | { kind: "completed" }
  | { kind: "failed" }
  | { kind: "ui_spec"; ui: UiSpecEvent }
  | { kind: "unknown" };

/**
 * Mirrors the `ui_spec` event of backend/api/runs.py: the json-render spec the server's model
 * wrote for one message, and the name of that message (`progress`, `proposal`, ...). The spec is
 * unchecked here: it is whatever the model replied, and lib/ui-catalog.ts checks it before it is
 * drawn.
 */
export type UiSpecEvent = { event: string; spec: Record<string, unknown> };

/** A UI spec the console draws. `id` is its position, so it is a stable key. */
export type UiMessage = UiSpecEvent & { id: number };

const UNKNOWN: RunEvent = { kind: "unknown" };

/** A message's data as JSON, or undefined when it is not: the callers refuse non-objects anyway. */
function parseData(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

export function parseRunEvent(message: SseMessage): RunEvent {
  switch (message.event) {
    case RUN_EVENTS.started: {
      const data = parseData(message.data);
      const runId = isRecord(data) ? data.run_id : undefined;
      return {
        kind: "started",
        runId: typeof runId === "string" ? runId : null,
      };
    }
    case RUN_EVENTS.reviewRequired:
      return { kind: "review" };
    case RUN_EVENTS.completed:
      return { kind: "completed" };
    case RUN_EVENTS.failed:
      return { kind: "failed" };
    case RUN_EVENTS.progress: {
      const progress = parseProgress(parseData(message.data));
      return progress ? { kind: "progress", progress } : UNKNOWN;
    }
    case RUN_EVENTS.uiSpec: {
      const data = parseData(message.data);
      if (!isRecord(data) || !isRecord(data.spec)) return UNKNOWN;
      if (typeof data.event !== "string") return UNKNOWN;
      return { kind: "ui_spec", ui: { event: data.event, spec: data.spec } };
    }
    default:
      return UNKNOWN;
  }
}

/**
 * How the stream ended, if this event ends it. `review` is a run that stopped at the human
 * review: its stream is over, the run is not.
 */
export type Outcome = "done" | "review" | "failed";

export function outcomeOf(event: RunEvent): Outcome | null {
  if (event.kind === "completed") return "done";
  if (event.kind === "review") return "review";
  return event.kind === "failed" ? "failed" : null;
}

/** True for run_failed and for a progress event that reports a failed step. */
export function isFailure(event: RunEvent): boolean {
  return (
    event.kind === "failed" ||
    (event.kind === "progress" && event.progress.event === "node_failed")
  );
}

/**
 * Adds the event's UI spec to the messages the console draws, if it is one; any other event
 * changes nothing. A pure fold: earlier messages keep their object identity, so a message only
 * re-renders when it is new.
 */
export function foldEvent(messages: UiMessage[], event: RunEvent): UiMessage[] {
  if (event.kind !== "ui_spec") return messages;
  return [...messages, { ...event.ui, id: messages.length }];
}
