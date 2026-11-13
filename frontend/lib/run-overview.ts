// What a run found, from GET /v1/runs/{id}/detail: read once into typed values, and the pipeline
// stepper of the run page drawn from them (and from the run's own stream while it
// runs). Mirrors runs.RunDetail (backend/runs/service.py) by hand.

import { type ClusterMap, isClusterMap } from "./cluster-map.ts";
import { formatCategory } from "./format.ts";
import { isRecord as isObj } from "./guards.ts";
import { diagnosesIn, type LiveProgress } from "./progress.ts";
import { isCount, isRunStatus, isText, plural } from "./runs.ts";
import { isNum } from "./traces.ts";
import { type Decision, MAX_JUDGED_TRACES, type RunStatus } from "./types.ts";

export type ClusterMethod = "hdbscan" | "step_error" | "isolated";
export type EvidenceCheck = "valid" | "corrected" | "unsupported";

export type Evidence = { trace_id: string; span_id: string; note: string };

/** The diagnoser's answer for one cluster; its prose is the model's own. */
export type ClusterDiagnosis = {
  category: string;
  root_cause: string;
  suggested_fix: string;
  confidence: number;
  evidence: Evidence[];
  evidence_check: EvidenceCheck;
  /** Healthy calls of the failing step the diagnoser was shown; null or missing for older runs. */
  healthy_twins?: number | null;
};

export type ClusterUsage = { calls: number; tokens: number; cost_usd: number };

export type ClusterDetail = {
  cluster_id: string;
  signature: string;
  method: ClusterMethod;
  trace_ids: string[];
  exemplar_trace_ids: string[];
  diagnosis: ClusterDiagnosis | null;
  diagnosis_failed: boolean;
  usage: ClusterUsage;
  verification: string;
  decision: Decision | null;
};

export type RunCounts = {
  run_id: string;
  traces: number;
  judged: number;
  judge_failures: number;
  failed_traces: number;
  clusters: number;
  unclustered: number;
  diagnoses: number;
  diagnosis_failures: number;
  proposals: number;
  actions_log: string[];
};

export type RunOverview = {
  status: RunStatus;
  /** It failed or was aborted with steps left in its checkpoint: it can be resumed from there. */
  resumable: boolean;
  summary: RunCounts;
  clusters: ClusterDetail[];
  /** The failures in 3D: null before clustering, for a run too small to embed, or an older run. */
  cluster_map: ClusterMap | null;
};

const isTexts = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every(isText);
const METHODS = new Set(["hdbscan", "step_error", "isolated"]);
export const isClusterMethod = (v: unknown): v is ClusterMethod =>
  METHODS.has(v as string);

/** How a cluster was formed, in words: the cards, the map's legend and its table say the same. */
export const METHOD_LABEL: Record<ClusterMethod, string> = {
  hdbscan: "similar failures",
  step_error: "same step and error",
  isolated: "isolated failure",
};

/** A cluster's title: its diagnosed category, or that it has none. */
export function clusterTitle(
  cluster: Pick<ClusterDetail, "diagnosis"> | undefined,
): string {
  return cluster?.diagnosis
    ? formatCategory(cluster.diagnosis.category)
    : "Undiagnosed failure";
}

/**
 * A cluster's signature split into the step that failed and the error it raised: the part before
 * the first ": " and the rest. A signature without one is all step (an error-free failure).
 */
export function signatureParts(signature: string): {
  step: string;
  error: string;
} {
  const at = signature.indexOf(": ");
  return at === -1
    ? { step: signature.trim(), error: "" }
    : {
        step: signature.slice(0, at).trim(),
        error: signature.slice(at + 2).trim(),
      };
}

export type ConfidenceLevel = "high" | "medium" | "low";

/** The diagnoser's confidence in a word: high from 0.75, medium from 0.5, low below. */
export function confidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.75) return "high";
  if (confidence >= 0.5) return "medium";
  return "low";
}

/** How the reproduction of a cluster stands, in words a reviewer reads. */
export function verificationText(verification: string): string {
  return verification === "unverified" ? "not reproduced yet" : verification;
}

/** What the diagnoser had to compare the failure with; null when the run did not record it. */
export function healthyTwinsText(
  count: number | null | undefined,
): string | null {
  if (count == null) return null;
  return count === 0
    ? "no healthy calls to compare with"
    : `compared with ${plural(count, "healthy call")}`;
}
const CHECKS = new Set(["valid", "corrected", "unsupported"]);

function isEvidence(v: unknown): v is Evidence {
  return isObj(v) && isText(v.trace_id) && isText(v.span_id) && isText(v.note);
}

function isDiagnosis(v: unknown): v is ClusterDiagnosis {
  return (
    isObj(v) &&
    isText(v.category) &&
    isText(v.root_cause) &&
    isText(v.suggested_fix) &&
    isNum(v.confidence) &&
    Array.isArray(v.evidence) &&
    v.evidence.every(isEvidence) &&
    CHECKS.has(v.evidence_check as string) &&
    (v.healthy_twins == null || isCount(v.healthy_twins))
  );
}

function isUsage(v: unknown): v is ClusterUsage {
  return isObj(v) && isCount(v.calls) && isCount(v.tokens) && isNum(v.cost_usd);
}

function isCluster(v: unknown): v is ClusterDetail {
  return (
    isObj(v) &&
    isText(v.cluster_id) &&
    isText(v.signature) &&
    isClusterMethod(v.method) &&
    isTexts(v.trace_ids) &&
    isTexts(v.exemplar_trace_ids) &&
    (v.diagnosis === null || isDiagnosis(v.diagnosis)) &&
    typeof v.diagnosis_failed === "boolean" &&
    isUsage(v.usage) &&
    isText(v.verification) &&
    (v.decision === null || v.decision === "approve" || v.decision === "reject")
  );
}

function isCounts(v: unknown): v is RunCounts {
  return (
    isObj(v) &&
    isText(v.run_id) &&
    isCount(v.traces) &&
    isCount(v.judged) &&
    isCount(v.judge_failures) &&
    isCount(v.failed_traces) &&
    isCount(v.clusters) &&
    isCount(v.unclustered) &&
    isCount(v.diagnoses) &&
    isCount(v.diagnosis_failures) &&
    isCount(v.proposals) &&
    isTexts(v.actions_log)
  );
}

/**
 * The whole run, or null when any part is off contract: never half a run. A missing
 * `cluster_map` (a backend from before the map) reads as null; a malformed one is off contract.
 */
export function parseRunOverview(body: unknown): RunOverview | null {
  if (
    !isObj(body) ||
    !isRunStatus(body.status) ||
    !isCounts(body.summary) ||
    !Array.isArray(body.clusters) ||
    !body.clusters.every(isCluster)
  )
    return null;
  const map = body.cluster_map ?? null;
  if (map !== null && !isClusterMap(map)) return null;
  return {
    ...(body as Omit<RunOverview, "cluster_map" | "resumable">),
    // Optional: a server from before resuming existed sends none.
    resumable: body.resumable === true,
    cluster_map: map,
  };
}

/**
 * Where a stage stands: finished, running now, waiting for a person, where the run failed or was
 * stopped, not reached yet, or not needed (nothing was found).
 */
export type StageState =
  | "done"
  | "running"
  | "waiting"
  | "failed"
  | "stopped"
  | "pending"
  | "skipped";

export type Stage = {
  key: StageKey;
  label: string;
  /** What the stage produced, in a few words ("48 traces"), or a dash. */
  detail: string;
  state: StageState;
  /** How far a running fan-out is, from 0 to 1 (the judge and the diagnoses); else null. */
  progress: number | null;
};

/** Where the run stands at the stage it reached, by its status. */
const AT: Record<RunStatus, StageState> = {
  in_progress: "running",
  review_required: "waiting",
  failed: "failed",
  aborted: "stopped",
  completed: "skipped", // ended with nothing left to do
};

/**
 * The graph's nodes of each stage, in order; the last one ends the stage, except for the
 * diagnoses, whose branches end one by one: that stage is done once the drafting starts.
 */
const NODES = {
  collect: ["collect_traces"],
  judge: ["score_trace", "join_scores"],
  cluster: ["cluster_failures"],
  diagnose: ["diagnose_cluster"],
  draft: ["draft_proposals"],
  review: ["human_review"],
  apply: ["apply_actions"],
} satisfies Record<string, string[]>;

export type StageKey = keyof typeof NODES;

/** An empty run, for a stream whose run has no checkpoint to read yet. */
export function emptyOverview(runId: string): RunOverview {
  return {
    status: "in_progress",
    resumable: false,
    summary: {
      run_id: runId,
      traces: 0,
      judged: 0,
      judge_failures: 0,
      failed_traces: 0,
      clusters: 0,
      unclustered: 0,
      diagnoses: 0,
      diagnosis_failures: 0,
      proposals: 0,
      actions_log: [],
    },
    clusters: [],
    cluster_map: null,
  };
}

/** States from the stream: the stage whose node runs is running, the ones before it are done. */
function liveStates(keys: StageKey[], live: LiveProgress): StageState[] {
  const reached = (i: number) =>
    keys
      .slice(i)
      .some(
        (k) =>
          NODES[k].some((n) => n in live.nodes) ||
          (k === "judge" && live.judge !== null),
      );
  const done = keys.map((k, i) => {
    const last = NODES[k].at(-1) as string;
    return reached(i + 1) || (k !== "diagnose" && live.nodes[last] === "done");
  });
  const at = done.indexOf(false);
  return keys.map((k, i) => {
    if (NODES[k].some((n) => live.nodes[n] === "failed")) return "failed";
    if (done[i]) return "done";
    if (i !== at) return "pending";
    return live.nodes.human_review === "paused" ? "waiting" : "running";
  });
}

/**
 * The graph's stages in order, each with what it produced in this run and where it stands. With
 * `live`, the progress of the run's own stream while it runs, the states come from the stream and
 * the counts from whichever of the two is further along.
 */
export function pipeline(
  { status, summary: s, clusters }: RunOverview,
  live: LiveProgress | null = null,
): Stage[] {
  const c = live?.counts ?? {};
  const n = {
    traces: Math.max(s.traces, c.traces ?? 0),
    failed: Math.max(s.failed_traces, c.failed_traces ?? 0),
    clusters: Math.max(s.clusters, c.clusters ?? 0),
    diagnoses: Math.max(s.diagnoses, live ? diagnosesIn(live, "done") : 0),
    diagnosisFailures: Math.max(
      s.diagnosis_failures,
      live ? diagnosesIn(live, "failed") : 0,
    ),
    proposals: Math.max(s.proposals, c.proposals ?? 0),
  };
  const isolated = clusters.filter((cl) => cl.method === "isolated").length;
  const judgedAny = s.judged + s.judge_failures;
  const approved = clusters.filter((cl) => cl.decision === "approve").length;
  const rejected = clusters.filter((cl) => cl.decision === "reject").length;
  const reviewed = approved + rejected > 0;
  const ended = status === "completed";
  const diagnosedAny = n.diagnoses + n.diagnosisFailures;
  const judgeDone = s.traces > 0 && judgedAny >= s.traces;

  const steps: {
    key: StageKey;
    label: string;
    detail: string;
    done: boolean;
  }[] = [
    {
      key: "collect",
      label: "Collect",
      detail:
        n.traces >= MAX_JUDGED_TRACES
          ? `${MAX_JUDGED_TRACES} newest traces`
          : plural(n.traces, "trace"),
      // A window with no traces ends the run here: collected, nothing to judge.
      done: n.traces > 0 || ended,
    },
    {
      key: "judge",
      label: "Judge",
      detail: judgeDone
        ? `${n.failed} failed of ${s.judged}` +
          (s.judge_failures > 0 ? ` · ${s.judge_failures} not judged` : "")
        : live?.judge
          ? `${live.judge.done} of ${live.judge.total} judged`
          : c.failed_traces !== undefined
            ? `${n.failed} failed`
            : "—",
      done: judgeDone,
    },
    {
      key: "cluster",
      label: "Cluster",
      detail:
        n.clusters > 0
          ? plural(n.clusters, "cluster") +
            (isolated > 0 ? ` · ${isolated} isolated` : "")
          : "—",
      done: n.clusters > 0,
    },
    {
      key: "diagnose",
      label: "Diagnose",
      detail:
        n.clusters > 0
          ? `${n.diagnoses} of ${n.clusters}` +
            (n.diagnosisFailures > 0 ? ` · ${n.diagnosisFailures} failed` : "")
          : "—",
      done: n.clusters > 0 && diagnosedAny >= n.clusters,
    },
    {
      key: "draft",
      label: "Draft",
      detail: n.proposals > 0 ? plural(n.proposals, "proposal") : "—",
      done: n.proposals > 0,
    },
    {
      key: "review",
      label: "Review",
      detail: reviewed
        ? `${approved} approved · ${rejected} rejected`
        : status === "review_required"
          ? `${plural(n.proposals, "proposal")} to decide`
          : "—",
      done: reviewed,
    },
    {
      key: "apply",
      label: "Apply",
      detail: reviewed ? plural(s.actions_log.length, "action") : "—",
      done: reviewed && ended,
    },
  ];

  const keys = steps.map((step) => step.key);
  let states: StageState[];
  if (live) {
    states = liveStates(keys, live);
  } else {
    // The first stage not done is where the run stands; the ones after it are not reached yet.
    const at = steps.findIndex((step) => !step.done);
    states = steps.map(({ done }, i) => {
      if (done) return "done";
      if (i === at) return AT[status];
      return ended ? "skipped" : "pending";
    });
  }

  return steps.map(({ key, label, detail }, i) => {
    let progress: number | null = null;
    if (states[i] === "running") {
      if (key === "judge" && live?.judge && live.judge.total > 0) {
        progress = live.judge.done / live.judge.total;
      }
      if (key === "diagnose" && n.clusters > 0) {
        progress = diagnosedAny / n.clusters;
      }
    }
    return { key, label, detail, state: states[i], progress };
  });
}

/** What the whole run spent on model calls. */
export function totalUsage(clusters: ClusterDetail[]): ClusterUsage {
  return clusters.reduce(
    (sum, c) => ({
      calls: sum.calls + c.usage.calls,
      tokens: sum.tokens + c.usage.tokens,
      cost_usd: sum.cost_usd + c.usage.cost_usd,
    }),
    { calls: 0, tokens: 0, cost_usd: 0 },
  );
}

/** Spend as "2 calls · 12,345 tokens · $0.012". */
export function formatUsage({ calls, tokens, cost_usd }: ClusterUsage): string {
  return `${plural(calls, "call")} · ${tokens.toLocaleString("en-US")} tokens · $${cost_usd.toFixed(3)}`;
}

/**
 * Whether the run collected as many traces as one run may judge: its window may hold older traces
 * that were never judged (MAX_JUDGED_TRACES).
 */
export function reachedTraceLimit(summary: Pick<RunCounts, "traces">): boolean {
  return summary.traces >= MAX_JUDGED_TRACES;
}
