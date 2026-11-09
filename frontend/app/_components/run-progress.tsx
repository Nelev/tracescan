"use client";

import {
  Check,
  CircleDashed,
  CircleSlash,
  Clock,
  Loader2,
  Minus,
  X,
} from "lucide-react";
import { memo } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type ClusterRow,
  type ClusterStatus,
  describeProgress,
  type RunView,
  type Stage,
  type StageStatus,
  type Totals,
  totals,
} from "@/lib/run-view";
import { cn } from "@/lib/utils";
import type { Phase } from "./use-run-stream";

type Status = StageStatus | ClusterStatus;

/** Icon, color and the word a screen reader hears. Status never rests on color alone. */
const STATUS: Record<
  Status,
  { Icon: typeof Check; className: string; word: string }
> = {
  pending: {
    Icon: CircleDashed,
    className: "text-muted-foreground",
    word: "Pending",
  },
  running: {
    Icon: Loader2,
    className: "text-ring motion-safe:animate-spin",
    word: "Running",
  },
  waiting: { Icon: Clock, className: "text-ring", word: "Waiting to retry" },
  done: { Icon: Check, className: "text-success", word: "Done" },
  failed: { Icon: X, className: "text-destructive", word: "Failed" },
  skipped: { Icon: Minus, className: "text-muted-foreground", word: "Skipped" },
  interrupted: {
    Icon: CircleSlash,
    className: "text-muted-foreground",
    word: "Interrupted",
  },
};

/** Singular and plural for the counts the graph reports (agent/progress.py COUNTED_KEYS). */
const COUNT_LABELS: Record<string, readonly [one: string, many: string]> = {
  failed_traces: ["failed trace", "failed traces"],
  clusters: ["cluster", "clusters"],
  unclustered: ["unclustered", "unclustered"],
  diagnoses: ["diagnosis", "diagnoses"],
  diagnosis_failures: ["diagnosis failure", "diagnosis failures"],
  reproductions: ["reproduction", "reproductions"],
  proposals: ["proposal", "proposals"],
  actions_log: ["action", "actions"],
};

function countText(key: string, value: number): string {
  const fallback = key.replaceAll("_", " ");
  const [one, many] = COUNT_LABELS[key] ?? [fallback, fallback];
  return `${value} ${value === 1 ? one : many}`;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)}s`;
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

const duration = (start?: number, end?: number) =>
  start === undefined || end === undefined ? "" : formatDuration(end - start);

function StatusIcon({ status }: { status: Status }) {
  const { Icon, className } = STATUS[status];
  return (
    <Icon aria-hidden="true" className={cn("size-4 shrink-0", className)} />
  );
}

function stageDetail(stage: Stage): string {
  switch (stage.status) {
    case "running":
      return stage.active > 1 ? `${stage.active} running` : "Running";
    case "pending":
      return "";
    case "done": {
      const counts = Object.entries(stage.counts).slice(0, 2);
      const text = counts
        .map(([key, value]) => countText(key, value))
        .join(" · ");
      return text || STATUS.done.word;
    }
    default:
      return STATUS[stage.status].word;
  }
}

// The view keeps a stage's object as it was until an event changes it, so memo skips the rest.
const StageItem = memo(function StageItem({ stage }: { stage: Stage }) {
  const dim = stage.status === "pending" || stage.status === "skipped";
  return (
    // Two lines are always reserved, so a row does not grow when its detail appears.
    <li className="flex min-h-11 items-start gap-3">
      <span className="flex h-[1.375rem] items-center">
        <StatusIcon status={stage.status} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span
            className={cn("type-body truncate", dim && "text-muted-foreground")}
          >
            <span className="sr-only">{STATUS[stage.status].word}: </span>
            {stage.label}
          </span>
          <span className="type-body shrink-0 text-muted-foreground tabular-nums">
            {duration(stage.startedAt, stage.endedAt)}
          </span>
        </div>
        <p className="type-body min-h-[1.375rem] truncate text-muted-foreground">
          {stageDetail(stage)}
        </p>
      </div>
    </li>
  );
});

/** What a cluster row says where it differs from the generic status word. */
const CLUSTER_TEXT: Partial<Record<ClusterStatus, string>> = {
  running: "Diagnosing",
  done: "Diagnosed",
  failed: "Diagnosis failed",
};

const ClusterItem = memo(function ClusterItem({ row }: { row: ClusterRow }) {
  return (
    <li className="grid grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-3 rounded-lg border bg-card px-3 py-2">
      <StatusIcon status={row.status} />
      <div className="min-w-0">
        <p className="type-body truncate font-mono">{row.clusterId}</p>
        <p className="type-body text-muted-foreground">
          {CLUSTER_TEXT[row.status] ?? STATUS[row.status].word}
          {row.attempts > 1 && ` · attempt ${row.attempts}`}
        </p>
      </div>
      <span className="type-body text-muted-foreground tabular-nums">
        {duration(row.startedAt, row.endedAt)}
      </span>
    </li>
  );
});

// Placeholders for clusters that are known but have not started, so the list has its final
// length at once. A fan-out starts every branch together, so they live for a moment only.
const MAX_SKELETONS = 6;

function emptyText(phase: Phase, t: Totals): string {
  if (phase === "idle") return "Run a triage to see its progress here.";
  if (phase === "running")
    return "Clusters appear once the failures are grouped.";
  if (t.failedTraces === 0) {
    return "No failed traces in this window, so there is nothing to diagnose.";
  }
  if (t.clusters === 0) return "No clusters: there was nothing to diagnose.";
  return "No clusters were diagnosed.";
}

function ClusterList({
  clusters,
  t,
  phase,
}: {
  clusters: ClusterRow[];
  t: Totals;
  phase: Phase;
}) {
  const waiting =
    phase === "running" && t.clusters !== undefined
      ? Math.min(Math.max(0, t.clusters - clusters.length), MAX_SKELETONS)
      : 0;

  if (clusters.length === 0 && waiting === 0) {
    return (
      <p className="type-body text-muted-foreground">{emptyText(phase, t)}</p>
    );
  }

  return (
    <ul aria-label="Clusters" className="flex flex-col gap-2">
      {clusters.map((row) => (
        <ClusterItem key={row.clusterId} row={row} />
      ))}
      {Array.from({ length: waiting }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: identical placeholders, never reordered
        <li key={i} aria-hidden="true">
          <Skeleton className="h-[3.375rem] rounded-lg" />
        </li>
      ))}
    </ul>
  );
}

export function RunProgress({ view, phase }: { view: RunView; phase: Phase }) {
  const t = totals(view);
  // Before clustering finishes the headline already says how many failed traces were found.
  const facts = [
    t.clusters !== undefined &&
      t.failedTraces !== undefined &&
      countText("failed_traces", t.failedTraces),
    t.unclustered !== undefined && countText("unclustered", t.unclustered),
  ].filter(Boolean);

  return (
    <div className="flex h-full flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
      <section
        aria-label="Pipeline"
        className="shrink-0 border-b p-4 lg:w-[22rem] lg:overflow-y-auto lg:border-r lg:border-b-0"
      >
        <ol className="flex flex-col gap-0.5">
          {view.stages.map((stage) => (
            <StageItem key={stage.node} stage={stage} />
          ))}
        </ol>
      </section>

      <section
        aria-label="Clusters"
        className="flex min-h-0 flex-1 flex-col gap-3 p-4 lg:overflow-y-auto"
      >
        <div className="min-h-11">
          {/* A polite live region: it changes when a cluster settles, not on every event. */}
          <output className="type-h3 block">{describeProgress(view, t)}</output>
          <p className="type-body min-h-[1.375rem] text-muted-foreground">
            {facts.join(" · ")}
          </p>
        </div>
        <ClusterList clusters={view.clusters} t={t} phase={phase} />
      </section>
    </div>
  );
}
