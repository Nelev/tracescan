import type { ProgressEvent, RunEvent, UiSpecEvent } from "./events.ts";

/**
 * The progress view of a run: a pure fold over the typed events. Nothing here touches React or
 * the DOM, and the renderer never reads events, so the view is plain, serialisable data.
 *
 * Unchanged stages and clusters keep their object identity from one fold to the next, so a row
 * only re-renders when its own data changed.
 */

export type StageStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "skipped"
  | "interrupted";

export type Stage = {
  node: string;
  label: string;
  status: StageStatus;
  /** Tasks of this node that started and have not reported back. A fan-out has several. */
  active: number;
  finished: number;
  failed: number;
  /** Counts summed over every task of this node. */
  counts: Record<string, number>;
  /** Milliseconds since the run started. */
  startedAt?: number;
  endedAt?: number;
};

export type ClusterStatus =
  | "running"
  /** An attempt ended with only its model usage recorded: the graph will run the node again. */
  | "waiting"
  | "done"
  | "failed"
  | "interrupted";

export type ClusterRow = {
  clusterId: string;
  status: ClusterStatus;
  /** How many times the diagnose node started for this cluster. */
  attempts: number;
  startedAt: number;
  endedAt?: number;
};

/** A UI spec the server sent, in arrival order. `id` is its position, so it is a stable key. */
export type UiMessage = UiSpecEvent & { id: number };

export type RunView = {
  stages: Stage[];
  clusters: ClusterRow[];
  /** What the console draws: the UI spec of each message the server's model laid out. */
  messages: UiMessage[];
};

/** The graph's nodes in run order (backend/agent/graph.py), with the label shown for each. */
const PIPELINE: readonly (readonly [node: string, label: string])[] = [
  ["collect_traces", "Collect traces"],
  ["cluster_failures", "Cluster failures"],
  ["diagnose_cluster", "Diagnose clusters"],
  ["join_diagnoses", "Join diagnoses"],
  ["reproduce_failure", "Reproduce failures"],
  ["match_known_issues", "Match known issues"],
  ["draft_proposals", "Draft proposals"],
  ["human_review", "Human review"],
  ["apply_actions", "Apply actions"],
];

/** The node whose tasks are one per cluster; only its tasks become cluster rows. */
const CLUSTER_NODE = "diagnose_cluster";

const labelOf = (node: string): string =>
  PIPELINE.find(([name]) => name === node)?.[1] ?? node.replaceAll("_", " ");

function newStage(node: string): Stage {
  return {
    node,
    label: labelOf(node),
    status: "pending",
    active: 0,
    finished: 0,
    failed: 0,
    counts: {},
  };
}

export const INITIAL_VIEW: RunView = {
  stages: PIPELINE.map(([node]) => newStage(node)),
  clusters: [],
  messages: [],
};

function stageStatus(stage: Stage): StageStatus {
  if (stage.active > 0) return "running";
  if (stage.failed > 0) return "failed";
  return stage.finished > 0 ? "done" : "pending";
}

function addCounts(
  into: Record<string, number>,
  more: Record<string, number> | undefined,
): Record<string, number> {
  if (!more) return into;
  const sum = { ...into };
  for (const [key, value] of Object.entries(more)) {
    sum[key] = (sum[key] ?? 0) + value;
  }
  return sum;
}

function foldStage(stage: Stage, p: ProgressEvent, at: number): Stage {
  const next = { ...stage, counts: addCounts(stage.counts, p.counts) };
  if (p.event === "node_started") {
    next.active += 1;
    next.startedAt ??= at;
    next.endedAt = undefined;
  } else {
    next.active = Math.max(0, next.active - 1);
    if (p.event === "node_failed") next.failed += 1;
    else next.finished += 1;
    if (next.active === 0) next.endedAt = at;
  }
  next.status = stageStatus(next);
  return next;
}

/** Where a cluster stands after one attempt ended. */
function settled(p: ProgressEvent): ClusterStatus {
  if (p.event === "node_failed") return "failed";
  const counts = p.counts ?? {};
  if (p.ok === false || (counts.diagnosis_failures ?? 0) > 0) return "failed";
  if ((counts.diagnoses ?? 0) > 0) return "done";
  // Neither a diagnosis nor a failure was written: a transient model error that the graph
  // retries after a wait, so the cluster is not finished.
  return "waiting";
}

function foldCluster(
  row: ClusterRow | undefined,
  clusterId: string,
  p: ProgressEvent,
  at: number,
): ClusterRow {
  const base: ClusterRow = row ?? {
    clusterId,
    status: "running",
    attempts: 0,
    startedAt: at,
  };
  if (p.event === "node_started") {
    return {
      ...base,
      status: "running",
      attempts: base.attempts + 1,
      endedAt: undefined,
    };
  }
  const status = settled(p);
  return {
    ...base,
    // A result with no start seen (a late join) still counts as one attempt.
    attempts: Math.max(1, base.attempts),
    status,
    endedAt: status === "waiting" ? undefined : at,
  };
}

/** Applies one event. `at` is milliseconds since the run started. */
export function foldEvent(view: RunView, event: RunEvent, at: number): RunView {
  if (event.kind === "ui_spec") {
    const messages = [
      ...view.messages,
      { ...event.ui, id: view.messages.length },
    ];
    return { ...view, messages };
  }
  if (event.kind !== "progress") return view;
  const p = event.progress;

  const idx = view.stages.findIndex((s) => s.node === p.node);
  const stages = [...view.stages];
  if (idx === -1) stages.push(foldStage(newStage(p.node), p, at));
  else stages[idx] = foldStage(stages[idx], p, at);

  let clusters = view.clusters;
  if (p.cluster_id !== undefined && p.node === CLUSTER_NODE) {
    const id = p.cluster_id;
    const i = clusters.findIndex((c) => c.clusterId === id);
    const next = foldCluster(clusters[i], id, p, at);
    clusters = i === -1 ? [...clusters, next] : clusters.with(i, next);
  }
  return { ...view, stages, clusters };
}

export type Ending = "done" | "failed" | "lost" | "cancelled";

/**
 * Settles the view when the run ends, so nothing keeps spinning. After a clean finish the stages
 * the run never reached (an early exit with no failures) are skipped; after any other ending
 * they stay pending, since the run did not get there.
 */
export function freezeView(view: RunView, ending: Ending): RunView {
  const stages = view.stages.map((s) => {
    if (s.status === "running") return { ...s, status: "interrupted" as const };
    if (s.status === "pending" && ending === "done") {
      return { ...s, status: "skipped" as const };
    }
    return s;
  });
  const clusters = view.clusters.map((c) =>
    c.status === "running" || c.status === "waiting"
      ? { ...c, status: "interrupted" as const }
      : c,
  );
  return { ...view, stages, clusters };
}

const countOf = (view: RunView, node: string, key: string) =>
  view.stages.find((s) => s.node === node)?.counts[key];

export type Totals = {
  failedTraces?: number;
  /** Known once clustering finishes. */
  clusters?: number;
  unclustered?: number;
  /** Clusters whose diagnosis is done or failed. */
  settled: number;
  failed: number;
};

export function totals(view: RunView): Totals {
  let settled = 0;
  let failed = 0;
  for (const c of view.clusters) {
    if (c.status === "failed") failed++;
    if (c.status === "failed" || c.status === "done") settled++;
  }
  return {
    failedTraces: countOf(view, "collect_traces", "failed_traces"),
    clusters: countOf(view, "cluster_failures", "clusters"),
    unclustered: countOf(view, "cluster_failures", "unclustered"),
    settled,
    failed,
  };
}

/** One sentence for the live region. It changes only when something a reader cares about does. */
export function describeProgress(
  view: RunView,
  t: Totals = totals(view),
): string {
  const failed = t.failed > 0 ? `, ${t.failed} failed` : "";
  const running = view.stages.find((s) => s.status === "running");
  if (
    t.clusters !== undefined &&
    (running?.node === CLUSTER_NODE || !running)
  ) {
    return `${t.settled} of ${t.clusters} clusters diagnosed${failed}`;
  }
  if (running) return `${running.label}…`;
  if (t.failedTraces !== undefined)
    return `${t.failedTraces} failed traces found`;
  return "";
}
