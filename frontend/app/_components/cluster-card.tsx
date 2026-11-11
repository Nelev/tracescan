"use client";

import {
  Check,
  ChevronDown,
  ChevronRight,
  type LucideIcon,
  Search,
  Wrench,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatCategory, formatPercent } from "@/lib/format";
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
import { TraceTree } from "./trace-tree";
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

type Pick = { traceId: string; spanId: string | null };

/**
 * The evidence the diagnosis rests on: each cited span as a numbered item, and the trace of the
 * picked one drawn below as a span tree, its cited spans starred with their notes. The traces the
 * diagnoser was shown without citing them can be opened too.
 */
function Evidence({ cluster }: { cluster: ClusterDetail }) {
  const evidence = cluster.diagnosis?.evidence ?? [];
  const cited = new Set(evidence.map((e) => e.trace_id));
  const uncited = cluster.exemplar_trace_ids.filter((t) => !cited.has(t));
  const [open, setOpen] = useState<Pick>(() =>
    evidence.length > 0
      ? { traceId: evidence[0].trace_id, spanId: evidence[0].span_id }
      : { traceId: cluster.exemplar_trace_ids[0], spanId: null },
  );
  const state = useTrace(open.traceId);
  const notes = new Map(
    evidence
      .filter((e) => e.trace_id === open.traceId)
      .map((e) => [e.span_id, e.note]),
  );

  return (
    <section
      aria-labelledby={`evidence-${cluster.cluster_id}`}
      className="flex flex-col gap-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 id={`evidence-${cluster.cluster_id}`} className="type-h3">
          Evidence
        </h4>
        <Link
          href={tracePath(open.traceId, open.spanId)}
          className="type-body underline decoration-muted-foreground/60 underline-offset-4 hover:decoration-foreground"
        >
          Open trace {shortId(open.traceId)} in full
        </Link>
      </div>
      {evidence.length > 0 ? (
        <ol className="flex flex-col gap-1.5">
          {evidence.map((e, i) => {
            const picked =
              e.trace_id === open.traceId && e.span_id === open.spanId;
            return (
              <li key={`${e.trace_id}:${e.span_id}`}>
                <button
                  type="button"
                  aria-pressed={picked}
                  onClick={() =>
                    setOpen({ traceId: e.trace_id, spanId: e.span_id })
                  }
                  className={cn(
                    "grid w-full grid-cols-[1.5rem_minmax(0,1fr)] gap-x-2 rounded-lg border px-3 py-2 text-left transition-colors hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    picked &&
                      "border-primary/60 bg-primary/10 hover:bg-primary/15",
                  )}
                >
                  <span
                    className={cn(
                      "flex size-6 items-center justify-center border font-mono",
                      picked &&
                        "border-primary bg-primary text-primary-foreground",
                    )}
                  >
                    {i + 1}
                  </span>
                  <span className="flex min-w-0 flex-col">
                    <span>{e.note}</span>
                    <span className="font-mono text-muted-foreground">
                      trace {shortId(e.trace_id)} · span {shortId(e.span_id)}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-muted-foreground">The diagnosis cites no span.</p>
      )}
      {uncited.length > 0 && (
        <fieldset className="flex flex-wrap items-center gap-1.5">
          <legend className="float-left mr-1 text-muted-foreground">
            Also shown to the diagnoser:
          </legend>
          {uncited.map((traceId) => (
            <Button
              key={traceId}
              size="sm"
              variant={traceId === open.traceId ? "secondary" : "ghost"}
              aria-pressed={traceId === open.traceId}
              onClick={() => setOpen({ traceId, spanId: null })}
              className="font-mono relative after:absolute after:inset-x-0 after:-inset-y-1.5 after:content-['']"
              title={traceId}
            >
              {shortId(traceId)}
            </Button>
          ))}
        </fieldset>
      )}
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
            cited={notes}
            initialSpan={open.spanId}
            layout="stacked"
          />
        )}
      </div>
    </section>
  );
}

/** A closed-by-default block of secondary detail, its summary always visible. */
function More({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <details className="group rounded-lg border">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="size-4 text-muted-foreground transition-transform group-open:rotate-90"
          aria-hidden="true"
        />
        <span className="type-h3">{title}</span>
      </summary>
      <div className="border-t p-3 motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-150">
        {children}
      </div>
    </details>
  );
}

/** Where the diagnosis stands for a cluster that has none yet, or lost it. */
function NoDiagnosis({
  cluster,
  live,
}: {
  cluster: ClusterDetail;
  live: LiveDiagnosis;
}) {
  if (cluster.diagnosis_failed) {
    return (
      <p className="text-destructive">
        The diagnosis failed. The cluster is kept, and its proposal is a stub.
      </p>
    );
  }
  if (live === "diagnosing") {
    return (
      <p className="flex items-center gap-2 text-muted-foreground">
        <Chip tone="info" size="sm" live>
          Diagnosing
        </Chip>
        The diagnoser is reading this cluster's traces.
      </p>
    );
  }
  return (
    <p className="text-muted-foreground">
      {live === "queued" ? "Queued for a diagnosis." : "Not diagnosed."}
    </p>
  );
}

/**
 * One cluster of failed traces and what the run made of it. Closed, it reads as a finding: the
 * diagnosed category, the root cause in a sentence or two, the failing step, and one line of
 * facts (size, confidence, evidence check). Opened from its footer, it shows the suggested fix,
 * the evidence as span trees, and the drafted issue and the cluster's traces folded away. The
 * diagnosis is the model's own prose, possibly clinical: shown, never logged. While the run waits
 * for review the header takes the reviewer's decision.
 */
export function ClusterCard({
  cluster,
  focused,
  live,
  proposal,
  decision,
  onDecide,
  deciding,
}: {
  cluster: ClusterDetail;
  /** The page was opened on this cluster: it starts open, scrolled into view and marked. */
  focused: boolean;
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
  const [expanded, setExpanded] = useState(focused);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "start" });
  }, [focused]);
  const { diagnosis } = cluster;
  const exemplars = new Set(cluster.exemplar_trace_ids);
  const shown = cluster.trace_ids.slice(0, MAX_TRACE_CHIPS);
  const hidden = cluster.trace_ids.length - shown.length;
  const detailsId = `cluster-${cluster.cluster_id}-details`;
  const cites = diagnosis?.evidence.length ?? 0;
  const check = diagnosis ? CHECK[diagnosis.evidence_check] : null;

  return (
    <article
      ref={ref}
      aria-labelledby={`cluster-${cluster.cluster_id}`}
      aria-current={focused ? "true" : undefined}
      className={cn(
        "type-body flex scroll-mt-20 flex-col overflow-hidden rounded-xl border bg-card",
        // A decided card carries a thin stripe of its decision, so a reviewed list scans at a
        // glance; one still to decide has no mark of its own: its picker is the cue.
        decision && "border-l-[3px]",
        decision === "approve" && "border-l-success/70",
        decision === "reject" && "border-l-muted-foreground/40",
        focused && "ring-1 ring-primary/50",
      )}
    >
      <div className="flex flex-col gap-3 p-4">
        <header className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
          <div className="flex min-w-0 flex-col gap-0.5">
            <h3
              id={`cluster-${cluster.cluster_id}`}
              className="type-h2 flex flex-wrap items-baseline gap-x-2"
            >
              {diagnosis
                ? formatCategory(diagnosis.category)
                : "Undiagnosed failure"}
              <span className="type-body font-normal text-muted-foreground">
                {plural(cluster.trace_ids.length, "failed trace")}
              </span>
            </h3>
            <p
              className="truncate font-mono text-muted-foreground"
              title={cluster.signature}
            >
              {cluster.signature}
            </p>
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
          <p className={cn("text-pretty", !expanded && "line-clamp-2")}>
            {diagnosis.root_cause}
          </p>
        ) : (
          <NoDiagnosis cluster={cluster} live={live} />
        )}

        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-muted-foreground">
          {diagnosis && (
            <li className="flex items-center gap-2">
              <span
                className="h-1.5 w-12 overflow-hidden bg-track"
                aria-hidden="true"
              >
                <span
                  className="block h-full bg-primary"
                  style={{ width: `${diagnosis.confidence * 100}%` }}
                />
              </span>
              {formatPercent(diagnosis.confidence)} confident
            </li>
          )}
          {check && (
            <li>
              <Chip tone={check.tone} size="sm">
                {check.label}
              </Chip>
            </li>
          )}
          <li>{METHOD[cluster.method]}</li>
          <li className="font-mono">{cluster.cluster_id}</li>
        </ul>
      </div>

      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((on) => !on)}
        className={cn(
          "flex w-full items-center justify-between gap-3 border-t px-4 py-2.5 text-left text-primary transition-colors hover:bg-primary/10 focus-visible:bg-primary/10 focus-visible:outline-none",
          expanded && "bg-primary/5",
        )}
      >
        <span className="type-h3 flex items-center gap-2 text-primary">
          <Search className="size-4" aria-hidden="true" />
          {expanded
            ? "Hide the evidence"
            : diagnosis
              ? `Show the evidence and the fix · ${plural(cites, "cited span")}`
              : "Show the traces"}
        </span>
        <ChevronDown
          className={cn(
            "size-4 transition-transform",
            expanded && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>

      {expanded && (
        <div
          id={detailsId}
          className="flex flex-col gap-5 border-t bg-background/20 p-4 motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-200"
        >
          {diagnosis && (
            <section
              aria-label="Suggested fix"
              className="flex gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3"
            >
              <Wrench
                className="mt-0.5 size-4 shrink-0 text-primary"
                aria-hidden="true"
              />
              <div className="flex flex-col gap-1">
                <h4 className="type-h3">Suggested fix</h4>
                <p>{diagnosis.suggested_fix}</p>
              </div>
            </section>
          )}
          {cluster.exemplar_trace_ids.length > 0 && (
            <Evidence cluster={cluster} />
          )}
          <div className="flex flex-col gap-2">
            {proposal && (
              <More title={`Drafted issue: ${proposal.title}`}>
                <div className="flex flex-col gap-3">
                  {issueSections(proposal.body).map(({ heading, text }) => (
                    <section key={heading} className="flex flex-col gap-1">
                      {heading && <h5 className="type-h3">{heading}</h5>}
                      <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">
                        {text}
                      </p>
                    </section>
                  ))}
                </div>
              </More>
            )}
            <More
              title={`All ${plural(cluster.trace_ids.length, "trace")} in the cluster`}
            >
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
                        "block rounded-md border px-2 font-mono hover:bg-hover focus-visible:bg-hover focus-visible:outline-none",
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
            </More>
          </div>
          <p className="type-h4 flex flex-wrap gap-x-4 gap-y-1">
            <span>Diagnosis: {formatUsage(cluster.usage)}</span>
            <span>{cluster.verification}</span>
          </p>
        </div>
      )}
    </article>
  );
}
