// The progress events of a run's stream (ProgressEvent in backend/agent/progress.py), read once
// and folded into where the run stands right now: which graph nodes started and finished, how far
// the trace judge is, and which clusters are being diagnosed. Ids and counts only: the server
// never sends a node's input or result.

import { isRecord } from "./guards.ts";

const KINDS = [
  "node_started",
  "node_finished",
  "node_failed",
  "node_paused",
  "node_progress",
] as const;

export type ProgressKind = (typeof KINDS)[number];

/** One progress event, as far as the page reads it. */
export type ProgressData = {
  event: ProgressKind;
  node: string;
  clusterId: string | null;
  /** False when a node finished but recorded a failure (a diagnosis that failed). */
  ok: boolean;
  counts: Record<string, number>;
};

const isKind = (v: unknown): v is ProgressKind =>
  (KINDS as readonly unknown[]).includes(v);

/** A progress event's data, or null when it is off contract. */
export function parseProgress(data: unknown): ProgressData | null {
  if (!isRecord(data)) return null;
  const { event, node, cluster_id, ok, counts } = data;
  if (!isKind(event) || typeof node !== "string") return null;
  const numbers: Record<string, number> = {};
  if (isRecord(counts)) {
    for (const [key, value] of Object.entries(counts)) {
      if (Number.isInteger(value)) numbers[key] = value as number;
    }
  }
  return {
    event,
    node,
    clusterId: typeof cluster_id === "string" ? cluster_id : null,
    ok: ok !== false,
    counts: numbers,
  };
}

export type NodeState = "running" | "done" | "failed" | "paused";

const STATE_OF: Record<Exclude<ProgressKind, "node_progress">, NodeState> = {
  node_started: "running",
  node_finished: "done",
  node_failed: "failed",
  node_paused: "paused",
};

/** Where a streamed run stands, from its progress events alone. */
export type LiveProgress = {
  /** The last state of each graph node that reported, by node name. */
  nodes: Record<string, NodeState>;
  /** Every count the finished nodes reported (traces, failed_traces, clusters, ...). */
  counts: Record<string, number>;
  /** The judge's fan-out: branches done of the total, once a quarter of them is. */
  judge: { done: number; total: number } | null;
  /**
   * Each diagnose branch's state, by cluster id: running, done, or failed (a branch that
   * finished without a diagnosis counts as failed).
   */
  diagnoses: Record<string, NodeState>;
  /**
   * Bumped whenever a node other than a diagnose branch ends: what the run's checkpoint holds
   * may have changed, so a page showing it loads it again.
   */
  checkpoints: number;
};

export const NO_PROGRESS: LiveProgress = {
  nodes: {},
  counts: {},
  judge: null,
  diagnoses: {},
  checkpoints: 0,
};

/** How many diagnose branches are in `state`. */
export const diagnosesIn = (live: LiveProgress, state: NodeState) =>
  Object.values(live.diagnoses).filter((s) => s === state).length;

/** The progress so far with one more event. Pure: the input is never changed. */
export function foldProgress(
  live: LiveProgress,
  p: ProgressData,
): LiveProgress {
  if (p.event === "node_progress") {
    const { done, total } = p.counts;
    return done === undefined || total === undefined
      ? live
      : { ...live, judge: { done, total } };
  }
  const state = STATE_OF[p.event];
  const next: LiveProgress = {
    ...live,
    nodes: { ...live.nodes, [p.node]: state },
    counts: { ...live.counts, ...p.counts },
  };
  if (p.node === "diagnose_cluster" && p.clusterId !== null) {
    next.diagnoses = {
      ...live.diagnoses,
      [p.clusterId]: state === "done" && !p.ok ? "failed" : state,
    };
    return next;
  }
  if (state !== "running") next.checkpoints = live.checkpoints + 1;
  return next;
}
