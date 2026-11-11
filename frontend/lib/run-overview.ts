// What a run found, from GET /v1/runs/{id}/detail: read once into typed values, and the pipeline
// the Run tab draws from them. Mirrors runs.RunDetail (backend/runs/service.py) by hand.

import { isRecord as isObj } from "./events.ts";
import { isCount, isRunStatus, isText, plural } from "./runs.ts";
import { isNum } from "./traces.ts";
import type { Decision, RunStatus } from "./types.ts";

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
  summary: RunCounts;
  clusters: ClusterDetail[];
};

const isTexts = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every(isText);
const METHODS = new Set(["hdbscan", "step_error", "isolated"]);
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
    CHECKS.has(v.evidence_check as string)
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
    METHODS.has(v.method as string) &&
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
    isCount(v.failed_traces) &&
    isCount(v.clusters) &&
    isCount(v.unclustered) &&
    isCount(v.diagnoses) &&
    isCount(v.diagnosis_failures) &&
    isCount(v.proposals) &&
    isTexts(v.actions_log)
  );
}

/** The whole run, or null when any part is off contract: never half a run. */
export function parseRunOverview(body: unknown): RunOverview | null {
  return isObj(body) &&
    isRunStatus(body.status) &&
    isCounts(body.summary) &&
    Array.isArray(body.clusters) &&
    body.clusters.every(isCluster)
    ? (body as RunOverview)
    : null;
}

/**
 * Where a stage stands: finished, running now, waiting for a person, where the run failed or was
 * stopped, not reached yet, not needed (nothing was found), or not part of the graph yet.
 */
export type StageState =
  | "done"
  | "running"
  | "waiting"
  | "failed"
  | "stopped"
  | "pending"
  | "skipped"
  | "not_built";

export type Stage = {
  key: string;
  label: string;
  detail: string;
  state: StageState;
};

/** Where the run stands at the stage it reached, by its status. */
const AT: Record<RunStatus, StageState> = {
  in_progress: "running",
  review_required: "waiting",
  failed: "failed",
  aborted: "stopped",
  completed: "skipped", // ended with nothing left to do
};

/** The graph's nodes in order, each with what it produced in this run and where it stands. */
export function pipeline({
  status,
  summary: s,
  clusters,
}: RunOverview): Stage[] {
  const isolated = clusters.filter((c) => c.method === "isolated").length;
  const approved = clusters.filter((c) => c.decision === "approve").length;
  const rejected = clusters.filter((c) => c.decision === "reject").length;
  const reviewed = approved + rejected > 0;
  const ended = status === "completed";

  // `done` is left out for a node the graph only has as a placeholder.
  const steps: {
    key: string;
    label: string;
    detail: string;
    done?: boolean;
  }[] = [
    {
      key: "collect",
      label: "Collect traces",
      detail: plural(s.failed_traces, "failed trace"),
      done:
        s.failed_traces > 0 ||
        ended ||
        status === "review_required" ||
        reviewed,
    },
    {
      key: "cluster",
      label: "Cluster",
      detail:
        plural(s.clusters, "cluster") +
        (isolated > 0 ? ` · ${isolated} isolated` : ""),
      done: s.clusters > 0,
    },
    {
      key: "diagnose",
      label: "Diagnose",
      detail:
        `${s.diagnoses} diagnosed` +
        (s.diagnosis_failures > 0 ? ` · ${s.diagnosis_failures} failed` : ""),
      done: s.clusters > 0 && s.diagnoses + s.diagnosis_failures >= s.clusters,
    },
    { key: "reproduce", label: "Reproduce", detail: "Not built yet" },
    { key: "match", label: "Match known issues", detail: "Not built yet" },
    {
      key: "draft",
      label: "Draft proposals",
      detail: plural(s.proposals, "proposal"),
      done: s.proposals > 0,
    },
    {
      key: "review",
      label: "Human review",
      detail: reviewed
        ? `${approved} approved · ${rejected} rejected`
        : status === "review_required"
          ? "Waiting for you"
          : "—",
      done: reviewed,
    },
    {
      key: "apply",
      label: "Apply (dry run)",
      detail: reviewed ? plural(s.actions_log.length, "action") : "—",
      done: reviewed && ended,
    },
  ];

  // The first stage not done is where the run stands; the ones after it are not reached yet.
  const at = steps.findIndex((step) => step.done === false);
  return steps.map(({ done, ...step }, i) => {
    let state: StageState;
    if (done === undefined) state = "not_built";
    else if (done) state = "done";
    else if (i === at) state = AT[status];
    else state = ended ? "skipped" : "pending";
    return { ...step, state };
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
