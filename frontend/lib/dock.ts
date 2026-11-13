// The console dock's words and counts: pure, so the chat box's badge and status are tested here.
import type { StatusTone } from "./runs.ts";

/** Where this window's run stands, as the stream knows it (use-run-stream.ts `Phase`). */
export type DockPhase =
  | "idle"
  | "running"
  | "done"
  | "review"
  | "failed"
  | "lost"
  | "cancelled";

/** Each phase in the dock's words, with the status tone of its chip. */
export const DOCK_STATUS: Record<
  DockPhase,
  { label: string; tone: StatusTone; line: string }
> = {
  idle: { label: "Starting", tone: "neutral", line: "Starting the run…" },
  running: {
    label: "Streaming",
    tone: "info",
    line: "The agent is working through the run.",
  },
  done: {
    label: "Finished",
    tone: "success",
    line: "The run finished with nothing to review.",
  },
  review: {
    label: "Awaiting review",
    tone: "warning",
    line: "The run waits for your review on its page.",
  },
  failed: { label: "Failed", tone: "destructive", line: "The run failed." },
  lost: {
    label: "Connection lost",
    tone: "destructive",
    line: "The connection to the run was lost. You can resume it from its page.",
  },
  cancelled: {
    label: "Stopped",
    tone: "stopped",
    line: "You stopped the run. You can resume it from its page.",
  },
};

/**
 * Where the run stands for the dock. A run whose graph has paused at the review waits for a
 * person, even while its stream still sends the proposals and their UI specs.
 */
export function dockPhase(phase: DockPhase, reviewPaused: boolean): DockPhase {
  return phase === "running" && reviewPaused ? "review" : phase;
}

/**
 * How many messages arrived since the panel was last open: none while it is open, and never
 * fewer than none (a new run starts the count again from its own first message).
 */
export function unreadCount(
  total: number,
  seen: number,
  open: boolean,
): number {
  return open ? 0 : Math.max(0, total - seen);
}

/** The launcher's badge: the count, capped so it stays one small mark. Empty for none. */
export function badgeText(count: number): string {
  if (count <= 0) return "";
  return count > 9 ? "9+" : String(count);
}

/** The count as a screen reader hears it, once, as a whole phrase. Empty for none. */
export function unreadText(count: number): string {
  if (count <= 0) return "";
  return `${count} new ${count === 1 ? "message" : "messages"} in the agent console`;
}
