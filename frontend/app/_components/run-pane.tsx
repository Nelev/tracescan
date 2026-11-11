"use client";

import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getRunOverview } from "@/lib/api";
import {
  type ClusterDetail,
  type EvidenceCheck,
  formatUsage,
  pipeline,
  type RunOverview,
  type Stage,
  type StageState,
  totalUsage,
} from "@/lib/run-overview";
import { plural, RUN_STATUS, type StatusTone, shortId } from "@/lib/runs";
import type { Decision } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import { LINK, PANE_HEIGHT } from "./console-styles";
import { Section } from "./traces-pane";
import { useResource } from "./use-list";

const STAGE: Record<StageState, { label: string; tone: StatusTone }> = {
  done: { label: "Done", tone: "success" },
  running: { label: "Running", tone: "info" },
  waiting: { label: "Waiting", tone: "warning" },
  failed: { label: "Failed", tone: "destructive" },
  stopped: { label: "Stopped", tone: "stopped" },
  pending: { label: "Pending", tone: "neutral" },
  skipped: { label: "Skipped", tone: "neutral" },
  not_built: { label: "Not built", tone: "neutral" },
};

const CHECK: Record<EvidenceCheck, { label: string; tone: StatusTone }> = {
  valid: { label: "Evidence valid", tone: "success" },
  corrected: { label: "Evidence corrected", tone: "neutral" },
  unsupported: { label: "Evidence unsupported", tone: "destructive" },
};

const METHOD: Record<ClusterDetail["method"], string> = {
  hdbscan: "Similar failures",
  step_error: "Same step and error",
  isolated: "Isolated failure",
};

const MAX_TRACE_CHIPS = 24;

function StageCard({ stage }: { stage: Stage }) {
  const { label, tone } = STAGE[stage.state];
  const notBuilt = stage.state === "not_built";
  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-lg border bg-card p-3",
        notBuilt && "border-dashed bg-transparent text-muted-foreground",
      )}
    >
      <span className="type-h4">{stage.label}</span>
      <span className="type-body">{stage.detail}</span>
      <span>
        <Chip tone={tone} size="sm" live={stage.state === "running"}>
          {label}
        </Chip>
      </span>
    </li>
  );
}

const DECISION: Record<
  Decision | "waiting",
  { label: string; tone: StatusTone }
> = {
  approve: { label: "Approved", tone: "success" },
  reject: { label: "Rejected", tone: "neutral" },
  waiting: { label: "Awaiting review", tone: "warning" },
};

function DecisionChip({
  cluster,
  waiting,
}: {
  cluster: ClusterDetail;
  waiting: boolean;
}) {
  const key = cluster.decision ?? (waiting ? "waiting" : null);
  if (key === null) return null;
  return (
    <Chip tone={DECISION[key].tone} size="sm">
      {DECISION[key].label}
    </Chip>
  );
}

function ClusterCard({
  cluster,
  waiting,
  onOpenTrace,
}: {
  cluster: ClusterDetail;
  waiting: boolean;
  onOpenTrace: (traceId: string, spanId: string | null) => void;
}) {
  const { diagnosis } = cluster;
  const exemplars = new Set(cluster.exemplar_trace_ids);
  const shown = cluster.trace_ids.slice(0, MAX_TRACE_CHIPS);
  const hidden = cluster.trace_ids.length - shown.length;
  return (
    <article className="type-body flex flex-col gap-4 rounded-xl border bg-card p-4">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="type-h3 font-mono">{cluster.cluster_id}</h3>
          <span className="text-muted-foreground">
            {plural(cluster.trace_ids.length, "trace")} ·{" "}
            {METHOD[cluster.method]}
          </span>
          <span className="ml-auto">
            <DecisionChip cluster={cluster} waiting={waiting} />
          </span>
        </div>
        <p className="font-mono text-muted-foreground [overflow-wrap:anywhere]">
          {cluster.signature}
        </p>
      </header>

      {diagnosis ? (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-md border px-2 font-mono">
              {diagnosis.category}
            </span>
            <span className="flex items-center gap-2">
              <span
                className="h-1.5 w-20 overflow-hidden rounded-full bg-foreground/10"
                aria-hidden="true"
              >
                <span
                  className="block h-full rounded-full bg-primary"
                  style={{ width: `${diagnosis.confidence * 100}%` }}
                />
              </span>
              <span className="tabular-nums">
                {Math.round(diagnosis.confidence * 100)}% confidence
              </span>
            </span>
            <Chip tone={CHECK[diagnosis.evidence_check].tone} size="sm">
              {CHECK[diagnosis.evidence_check].label}
            </Chip>
          </div>
          <Section title="Root cause">
            <p>{diagnosis.root_cause}</p>
          </Section>
          <Section title="Suggested fix">
            <p>{diagnosis.suggested_fix}</p>
          </Section>
          <Section title="Evidence">
            <ul className="flex flex-col gap-2">
              {diagnosis.evidence.map((e) => (
                <li
                  key={`${e.trace_id}:${e.span_id}`}
                  className="flex flex-col gap-0.5"
                >
                  <button
                    type="button"
                    onClick={() => onOpenTrace(e.trace_id, e.span_id)}
                    className={cn(LINK, "flex w-fit items-center gap-1")}
                    aria-label={`Open span ${e.span_id} of trace ${shortId(e.trace_id)}`}
                  >
                    {shortId(e.trace_id)}
                    <ChevronRight className="size-3.5" aria-hidden="true" />
                    {e.span_id}
                  </button>
                  <span className="text-muted-foreground">{e.note}</span>
                </li>
              ))}
            </ul>
          </Section>
        </>
      ) : (
        <p
          className={
            cluster.diagnosis_failed
              ? "text-destructive"
              : "text-muted-foreground"
          }
        >
          {cluster.diagnosis_failed
            ? "The diagnosis failed. The cluster is kept, and its proposal is a stub."
            : "Not diagnosed yet."}
        </p>
      )}

      <Section title="Traces">
        <ul className="flex flex-wrap gap-1.5">
          {shown.map((traceId) => (
            <li key={traceId}>
              <button
                type="button"
                onClick={() => onOpenTrace(traceId, null)}
                title={
                  exemplars.has(traceId)
                    ? `${traceId} (shown to the diagnoser)`
                    : traceId
                }
                className={cn(
                  "rounded-md border px-2 font-mono hover:bg-foreground/5 focus-visible:bg-foreground/5 focus-visible:outline-none",
                  exemplars.has(traceId) && "border-primary/60 text-primary",
                )}
              >
                {shortId(traceId)}
              </button>
            </li>
          ))}
          {hidden > 0 && (
            <li className="px-2 text-muted-foreground">+{hidden} more</li>
          )}
        </ul>
      </Section>

      <footer className="type-h4 flex flex-wrap gap-x-4 gap-y-1">
        <span>{formatUsage(cluster.usage)}</span>
        <span>{cluster.verification}</span>
      </footer>
    </article>
  );
}

function Overview({
  overview,
  onOpenTrace,
  onReview,
}: {
  overview: RunOverview;
  onOpenTrace: (traceId: string, spanId: string | null) => void;
  onReview: (runId: string) => void;
}) {
  const { status, summary, clusters } = overview;
  const { label, tone } = RUN_STATUS[status];
  const waiting = status === "review_required";
  return (
    <div className="flex flex-col gap-6 p-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Chip tone={tone} size="sm">
          {label}
        </Chip>
        <span className="type-body font-mono">{summary.run_id}</span>
        {clusters.length > 0 && (
          <span className="type-body text-muted-foreground">
            {formatUsage(totalUsage(clusters))}
          </span>
        )}
        {waiting && (
          <Button className="ml-auto" onClick={() => onReview(summary.run_id)}>
            Review proposals
          </Button>
        )}
      </div>

      <section className="flex flex-col gap-3">
        <h3 className="type-h4">Pipeline</h3>
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 2xl:grid-cols-8">
          {pipeline(overview).map((stage) => (
            <StageCard key={stage.key} stage={stage} />
          ))}
        </ol>
      </section>

      <section className="flex flex-col gap-3">
        <h3 className="type-h4">Clusters</h3>
        {clusters.length === 0 ? (
          <p className="type-body text-muted-foreground">
            {status === "completed"
              ? "This run found no failures to cluster."
              : "No clusters yet."}
          </p>
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {clusters.map((cluster) => (
              <ClusterCard
                key={cluster.cluster_id}
                cluster={cluster}
                waiting={waiting}
                onOpenTrace={onOpenTrace}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

/**
 * What one run found: the pipeline with each stage's output, then each cluster with its
 * signature, diagnosis, cited spans and traces (each opens under Traces), spend and decision.
 * The diagnoses' prose is the model's own, possibly clinical: shown, never logged.
 */
export function RunPane({
  runId,
  visible,
  reloadOn,
  onOpenTrace,
  onReview,
}: {
  runId: string;
  /** Loads only while shown; a panel shown again with nothing changed loads nothing. */
  visible: boolean;
  /** Changes when what the run shows can have changed: a review, a phase of this page's run. */
  reloadOn: string;
  onOpenTrace: (traceId: string, spanId: string | null) => void;
  onReview: (runId: string) => void;
}) {
  const state = useResource(
    (signal) => getRunOverview(runId, signal),
    visible,
    reloadOn,
  );
  return (
    <div className={cn(PANE_HEIGHT, "overflow-auto")}>
      {state.status === "loading" && state.value === null && (
        <p className="type-body p-4 text-muted-foreground">Loading run…</p>
      )}
      {state.status === "error" && (
        <p role="alert" className="type-body p-4 text-destructive">
          {state.missing
            ? "The server does not know this run."
            : "Could not load the run. Check that the backend is running, then open it again."}
        </p>
      )}
      {state.value && (
        <Overview
          overview={state.value}
          onOpenTrace={onOpenTrace}
          onReview={onReview}
        />
      )}
    </div>
  );
}
