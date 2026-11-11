"use client";

import { Check, ChevronDown, type LucideIcon, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { formatPercent } from "@/lib/format";
import { issueSections, type Proposal } from "@/lib/review";
import {
  type ClusterDetail,
  type EvidenceCheck,
  formatUsage,
} from "@/lib/run-overview";
import { plural, type StatusTone, shortId } from "@/lib/runs";
import { tracePath } from "@/lib/traces";
import type { Decision } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import { SEGMENT_ITEM, SEGMENT_LIST } from "./styles";
import { Section, TraceTree } from "./trace-tree";
import { useTrace } from "./use-traces";

const CHECK: Record<EvidenceCheck, { label: string; tone: StatusTone }> = {
  valid: { label: "Evidence valid", tone: "success" },
  corrected: { label: "Evidence corrected", tone: "neutral" },
  unsupported: { label: "Evidence unsupported", tone: "destructive" },
};

const METHOD: Record<ClusterDetail["method"], string> = {
  hdbscan: "similar failures",
  step_error: "same step and error",
  isolated: "isolated failure",
};

/** Where a cluster's diagnosis stands while the run streams. */
export type LiveDiagnosis = "queued" | "diagnosing" | null;

const MAX_TRACE_CHIPS = 24;

const OPTIONS: {
  value: Decision;
  label: string;
  Icon: LucideIcon;
  chosen: string;
}[] = [
  {
    value: "approve",
    label: "Approve",
    Icon: Check,
    chosen: "bg-success/10 text-success hover:text-success",
  },
  {
    value: "reject",
    label: "Reject",
    Icon: X,
    chosen: "bg-destructive/10 text-destructive hover:text-destructive",
  },
];

function DecisionPicker({
  clusterId,
  decision,
  disabled,
  onDecide,
}: {
  clusterId: string;
  decision: Decision | undefined;
  disabled: boolean;
  onDecide: (decision: Decision) => void;
}) {
  return (
    <fieldset disabled={disabled} className="shrink-0 disabled:opacity-50">
      <legend className="sr-only">Decision for {clusterId}</legend>
      <div className={SEGMENT_LIST}>
        {OPTIONS.map(({ value, label, Icon, chosen }) => (
          <label
            key={value}
            className={cn(
              SEGMENT_ITEM,
              "inline-flex items-center gap-1.5",
              decision === value && chosen,
            )}
          >
            <input
              type="radio"
              name={`decision-${clusterId}`}
              value={value}
              checked={decision === value}
              onChange={() => onDecide(value)}
              className="sr-only"
            />
            <Icon className="size-4" aria-hidden="true" />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

const DECIDED: Record<Decision, { label: string; tone: StatusTone }> = {
  approve: { label: "Approved", tone: "success" },
  reject: { label: "Rejected", tone: "neutral" },
};

/**
 * The traces the diagnoser was shown, one at a time, as trees with the cited spans marked. Only
 * for a cluster with exemplars (every cluster has at least one).
 */
function ExemplarTrees({ cluster }: { cluster: ClusterDetail }) {
  const evidence = cluster.diagnosis?.evidence ?? [];
  // The cited traces first: they are the ones the diagnosis rests on.
  const citedTraces = new Set(evidence.map((e) => e.trace_id));
  const traces = [
    ...cluster.exemplar_trace_ids.filter((t) => citedTraces.has(t)),
    ...cluster.exemplar_trace_ids.filter((t) => !citedTraces.has(t)),
    ...[...citedTraces].filter((t) => !cluster.exemplar_trace_ids.includes(t)),
  ];
  const [open, setOpen] = useState<{ traceId: string; spanId: string | null }>(
    () => ({ traceId: traces[0], spanId: null }),
  );
  const state = useTrace(open.traceId);
  const cited = new Map(
    evidence
      .filter((e) => e.trace_id === open.traceId)
      .map((e) => [e.span_id, e.note]),
  );

  return (
    <Section title="Evidence in the traces">
      {evidence.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {evidence.map((e) => (
            <li key={`${e.trace_id}:${e.span_id}`} className="flex flex-col">
              <button
                type="button"
                onClick={() =>
                  setOpen({ traceId: e.trace_id, spanId: e.span_id })
                }
                className="w-fit text-left font-mono text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none"
              >
                {shortId(e.trace_id)} › {e.span_id}
              </button>
              <span className="text-muted-foreground">{e.note}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <fieldset className="flex flex-wrap gap-1.5">
          <legend className="sr-only">Traces shown to the diagnoser</legend>
          {traces.map((traceId, i) => (
            <Button
              key={traceId}
              size="sm"
              variant={traceId === open.traceId ? "secondary" : "ghost"}
              aria-pressed={traceId === open.traceId}
              onClick={() => setOpen({ traceId, spanId: null })}
              className="font-mono"
              title={traceId}
            >
              {i + 1}. {shortId(traceId)}
            </Button>
          ))}
        </fieldset>
        <Link
          href={tracePath(open.traceId, open.spanId)}
          className="type-body text-primary underline-offset-4 hover:underline"
        >
          Open full trace
        </Link>
      </div>
      <div className="overflow-hidden rounded-lg border bg-background/40">
        {state.status === "loading" && state.value === null && (
          <p className="type-body p-3 text-muted-foreground">Loading trace…</p>
        )}
        {state.status === "error" && (
          <p role="alert" className="type-body p-3 text-destructive">
            {state.missing
              ? "The trace store has no whole trace by this id."
              : "Could not load the trace."}
          </p>
        )}
        {state.value && state.value.trace_id === open.traceId && (
          <TraceTree
            key={`${open.traceId}:${open.spanId}`}
            trace={state.value}
            cited={cited}
            initialSpan={open.spanId}
            layout="stacked"
          />
        )}
      </div>
    </Section>
  );
}

/**
 * One cluster of failed traces and what the run made of it: the signature, the diagnosis (the
 * model's own prose, possibly clinical: shown, never logged), and, opened, the evidence as span
 * trees, the drafted issue, the cluster's traces and its spend. While the run waits for review it
 * also takes the reviewer's decision.
 */
export function ClusterCard({
  cluster,
  live,
  proposal,
  decision,
  onDecide,
  deciding,
}: {
  cluster: ClusterDetail;
  live: LiveDiagnosis;
  /** The drafted issue, once the proposals are loaded for review. */
  proposal: Proposal | null;
  /** The reviewer's pick so far (while reviewing) or the recorded one. */
  decision: Decision | undefined;
  /** Set while the run waits for review and takes decisions. */
  onDecide: ((decision: Decision) => void) | null;
  /** The decisions are being sent. */
  deciding: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const { diagnosis } = cluster;
  const exemplars = new Set(cluster.exemplar_trace_ids);
  const shown = cluster.trace_ids.slice(0, MAX_TRACE_CHIPS);
  const hidden = cluster.trace_ids.length - shown.length;
  const detailsId = `cluster-${cluster.cluster_id}-details`;

  return (
    <article
      aria-labelledby={`cluster-${cluster.cluster_id}`}
      className={cn(
        "type-body flex flex-col gap-3 rounded-xl border bg-card p-4",
        expanded && "border-foreground/20",
        onDecide && decision === undefined && "border-warning/40",
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h3
            id={`cluster-${cluster.cluster_id}`}
            className="flex flex-wrap items-baseline gap-x-2 font-mono [overflow-wrap:anywhere]"
          >
            <span className="text-muted-foreground">{cluster.cluster_id}</span>
            {cluster.signature}
          </h3>
          <span className="text-muted-foreground">
            {plural(cluster.trace_ids.length, "trace")} ·{" "}
            {METHOD[cluster.method]}
          </span>
        </div>
        {onDecide ? (
          <DecisionPicker
            clusterId={cluster.cluster_id}
            decision={decision}
            disabled={deciding}
            onDecide={onDecide}
          />
        ) : (
          decision && (
            <Chip tone={DECIDED[decision].tone} size="sm">
              {DECIDED[decision].label}
            </Chip>
          )
        )}
      </header>

      {diagnosis ? (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-md border px-2 font-mono">
              {diagnosis.category}
            </span>
            <span className="flex items-center gap-2">
              <span
                className="h-1.5 w-16 overflow-hidden rounded-full bg-foreground/10"
                aria-hidden="true"
              >
                <span
                  className="block h-full rounded-full bg-primary"
                  style={{ width: `${diagnosis.confidence * 100}%` }}
                />
              </span>
              <span className="tabular-nums">
                {formatPercent(diagnosis.confidence)} confidence
              </span>
            </span>
            <Chip tone={CHECK[diagnosis.evidence_check].tone} size="sm">
              {CHECK[diagnosis.evidence_check].label}
            </Chip>
          </div>
          <p className={cn(!expanded && "line-clamp-2")}>
            {diagnosis.root_cause}
          </p>
        </>
      ) : (
        <p
          className={cn(
            cluster.diagnosis_failed
              ? "text-destructive"
              : "text-muted-foreground",
            "flex items-center gap-2",
          )}
        >
          {live === "diagnosing" && (
            <Chip tone="info" size="sm" live>
              Diagnosing
            </Chip>
          )}
          {cluster.diagnosis_failed
            ? "The diagnosis failed. The cluster is kept, and its proposal is a stub."
            : live === "diagnosing"
              ? "The diagnoser is reading this cluster's traces."
              : live === "queued"
                ? "Queued for a diagnosis."
                : "Not diagnosed."}
        </p>
      )}

      <Button
        variant="ghost"
        size="sm"
        className="-ml-2 w-fit"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((on) => !on)}
      >
        <ChevronDown
          className={cn("transition-transform", expanded && "rotate-180")}
          aria-hidden="true"
        />
        {expanded ? "Hide details" : "Evidence, traces and issue"}
      </Button>

      {expanded && (
        <div id={detailsId} className="flex flex-col gap-5">
          {diagnosis && (
            <Section title="Suggested fix">
              <p>{diagnosis.suggested_fix}</p>
            </Section>
          )}
          {cluster.exemplar_trace_ids.length > 0 && (
            <ExemplarTrees cluster={cluster} />
          )}
          {proposal && (
            <Section title="Drafted issue">
              <div className="flex flex-col gap-3 rounded-lg border p-3">
                <p className="type-h3 [overflow-wrap:anywhere]">
                  {proposal.title}
                </p>
                {issueSections(proposal.body).map(({ heading, text }) => (
                  <section key={heading} className="flex flex-col gap-1">
                    {heading && <h5 className="type-h3">{heading}</h5>}
                    <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">
                      {text}
                    </p>
                  </section>
                ))}
              </div>
            </Section>
          )}
          <Section title="All traces in the cluster">
            <ul className="flex flex-wrap gap-1.5">
              {shown.map((traceId) => (
                <li key={traceId}>
                  <Link
                    href={tracePath(traceId)}
                    title={
                      exemplars.has(traceId)
                        ? `${traceId} (shown to the diagnoser)`
                        : traceId
                    }
                    className={cn(
                      "block rounded-md border px-2 font-mono hover:bg-foreground/5 focus-visible:bg-foreground/5 focus-visible:outline-none",
                      exemplars.has(traceId) &&
                        "border-primary/60 text-primary",
                    )}
                  >
                    {shortId(traceId)}
                  </Link>
                </li>
              ))}
              {hidden > 0 && (
                <li className="px-2 text-muted-foreground">+{hidden} more</li>
              )}
            </ul>
          </Section>
          <p className="type-h4 flex flex-wrap gap-x-4 gap-y-1">
            <span>{formatUsage(cluster.usage)}</span>
            <span>{cluster.verification}</span>
          </p>
        </div>
      )}
    </article>
  );
}
