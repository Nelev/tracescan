"use client";

import { Check, ChevronLeft, ChevronRight, X } from "lucide-react";
import {
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Button } from "@/components/ui/button";
import { formatPercent } from "@/lib/format";
import type { Proposal } from "@/lib/review";
import {
  type ClusterDetail,
  type ConfidenceLevel,
  clusterTitle,
  confidenceLevel,
  signatureParts,
} from "@/lib/run-overview";
import { plural } from "@/lib/runs";
import type { Decision } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ClusterCard, type LiveDiagnosis } from "./cluster-card";

/** Wide enough for the list and the detail side by side (Tailwind's `xl`). */
const WIDE = "(min-width: 80rem)";

function subscribeWide(onChange: () => void): () => void {
  const query = window.matchMedia(WIDE);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** Whether the list and the detail sit side by side; below `xl` the detail opens under its row. */
function useWide(): boolean {
  return useSyncExternalStore(
    subscribeWide,
    () => window.matchMedia(WIDE).matches,
    () => false,
  );
}

const CONFIDENCE: Record<ConfidenceLevel, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

/** A finding the run page asked for (a linked cluster, or the map's Open finding). */
export type FindingAsk = { clusterId: string; ask: number } | null;

type Props = {
  clusters: ClusterDetail[];
  /** Set when the page asks for one finding; a new `ask` each time, so asking again shows it. */
  ask: FindingAsk;
  proposals: Map<string, Proposal>;
  decisionOf: (cluster: ClusterDetail) => Decision | undefined;
  /** The run waits for review: undecided findings are marked, and the cards take decisions. */
  deciding: boolean;
  onDecide: ((clusterId: string, decision: Decision) => void) | null;
  /** The decisions are being sent. */
  sending: boolean;
  live: (clusterId: string) => LiveDiagnosis;
};

/**
 * The run's findings, readable at a glance: every finding as one compact row (its kind, the error
 * seen, its size as a bar, how sure the diagnosis is, where its decision stands), and the picked
 * one in full beside the list on a wide screen, under its own row otherwise. Up and Down move
 * through the rows; the detail steps to the previous, the next, or the next one still to decide.
 * It opens on the finding the page asked for, else the first one to decide, else the first.
 */
export function FindingsBrowser({
  clusters,
  ask,
  proposals,
  decisionOf,
  deciding,
  onDecide,
  sending,
  live,
}: Props) {
  const wide = useWide();
  const [selected, setSelected] = useState<string>(
    () =>
      ask?.clusterId ??
      (deciding
        ? clusters.find((c) => decisionOf(c) === undefined)?.cluster_id
        : undefined) ??
      clusters[0].cluster_id,
  );
  const rows = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    if (ask) setSelected(ask.clusterId);
  }, [ask]);

  const index = Math.max(
    0,
    clusters.findIndex((c) => c.cluster_id === selected),
  );
  const current = clusters[index];
  const maxTraces = Math.max(...clusters.map((c) => c.trace_ids.length));
  const nextUndecided = deciding
    ? [...clusters.slice(index + 1), ...clusters.slice(0, index)].find(
        (c) => decisionOf(c) === undefined,
      )
    : undefined;

  function select(clusterId: string, focusRow = false) {
    setSelected(clusterId);
    if (focusRow) rows.current.get(clusterId)?.focus();
  }

  function onKeyDown(event: KeyboardEvent) {
    const step: Record<string, number> = {
      ArrowDown: index + 1,
      ArrowUp: index - 1,
      Home: 0,
      End: clusters.length - 1,
    };
    const to = step[event.key];
    if (to === undefined) return;
    event.preventDefault();
    const next = clusters[Math.min(clusters.length - 1, Math.max(0, to))];
    select(next.cluster_id, true);
  }

  const detail = (
    <div className="flex min-w-0 flex-col gap-3">
      <nav
        aria-label="Step through the findings"
        className="flex flex-wrap items-center gap-2"
      >
        <span className="type-h4 mr-auto">
          Finding {index + 1} of {clusters.length}
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={index === 0}
          onClick={() => select(clusters[index - 1].cluster_id)}
        >
          <ChevronLeft aria-hidden="true" />
          Previous
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={index === clusters.length - 1}
          onClick={() => select(clusters[index + 1].cluster_id)}
        >
          Next
          <ChevronRight aria-hidden="true" />
        </Button>
        {nextUndecided && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => select(nextUndecided.cluster_id)}
          >
            Next to decide
            <ChevronRight aria-hidden="true" />
          </Button>
        )}
      </nav>
      <ClusterCard
        key={current.cluster_id}
        cluster={current}
        focus={ask?.clusterId === current.cluster_id ? ask.ask : null}
        live={live(current.cluster_id)}
        proposal={proposals.get(current.cluster_id) ?? null}
        decision={decisionOf(current)}
        onDecide={onDecide ? (d) => onDecide(current.cluster_id, d) : null}
        deciding={sending}
      />
    </div>
  );

  return (
    <div className="grid items-start gap-6 xl:grid-cols-[24rem_minmax(0,1fr)]">
      <ol
        aria-label="Findings in this run"
        onKeyDown={onKeyDown}
        className="flex min-w-0 flex-col gap-1.5 xl:sticky xl:top-20"
      >
        {clusters.map((c) => {
          const isSelected = c.cluster_id === current.cluster_id;
          return (
            <li key={c.cluster_id} className="flex flex-col gap-3">
              <Row
                cluster={c}
                ref={(el) => {
                  if (el) rows.current.set(c.cluster_id, el);
                  else rows.current.delete(c.cluster_id);
                }}
                selected={isSelected}
                maxTraces={maxTraces}
                decision={decisionOf(c)}
                deciding={deciding}
                live={live(c.cluster_id)}
                onSelect={() => select(c.cluster_id)}
              />
              {!wide && isSelected && detail}
            </li>
          );
        })}
      </ol>
      {wide && detail}
    </div>
  );
}

/** Where a finding's decision stands, as a mark and a word, so it never rests on color alone. */
function DecisionMark({
  decision,
  deciding,
}: {
  decision: Decision | undefined;
  deciding: boolean;
}) {
  if (decision === "approve") {
    return (
      <span className="flex items-center gap-1 text-success">
        <Check className="size-4" aria-hidden="true" />
        Approved
      </span>
    );
  }
  if (decision === "reject") {
    return (
      <span className="flex items-center gap-1 text-muted-foreground">
        <X className="size-4" aria-hidden="true" />
        Rejected
      </span>
    );
  }
  if (!deciding) return null;
  return (
    <span className="flex items-center gap-1.5 text-warning">
      <span className="size-2 rounded-full bg-current" aria-hidden="true" />
      To decide
    </span>
  );
}

/** One finding in the list: two short lines and a size bar, the whole row one button. */
function Row({
  cluster,
  ref,
  selected,
  maxTraces,
  decision,
  deciding,
  live,
  onSelect,
}: {
  cluster: ClusterDetail;
  ref: (el: HTMLButtonElement | null) => void;
  selected: boolean;
  maxTraces: number;
  decision: Decision | undefined;
  deciding: boolean;
  live: LiveDiagnosis;
  onSelect: () => void;
}) {
  const { step, error } = signatureParts(cluster.signature);
  const traces = cluster.trace_ids.length;
  const { diagnosis } = cluster;
  const sureness =
    live === "diagnosing"
      ? "Diagnosing…"
      : live === "queued"
        ? "Queued"
        : diagnosis
          ? `${CONFIDENCE[confidenceLevel(diagnosis.confidence)]} confidence · ${formatPercent(diagnosis.confidence)}`
          : cluster.diagnosis_failed
            ? "Diagnosis failed"
            : "Not diagnosed";

  return (
    <button
      ref={ref}
      type="button"
      aria-current={selected ? "true" : undefined}
      onClick={onSelect}
      className={cn(
        "type-body grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-xl border px-3 py-2.5 text-left transition-colors hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-primary/60 bg-primary/10 hover:bg-primary/15"
          : "surface",
      )}
    >
      <span className="type-h3 truncate">{clusterTitle(cluster)}</span>
      <DecisionMark decision={decision} deciding={deciding} />
      <span
        className="col-span-2 truncate font-mono text-muted-foreground"
        title={cluster.signature}
      >
        {error || step}
      </span>
      <span className="col-span-2 flex items-center gap-2 text-muted-foreground">
        <span
          className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-track"
          aria-hidden="true"
        >
          <span
            className="block h-full rounded-full bg-primary"
            style={{ width: `${(traces / maxTraces) * 100}%` }}
          />
        </span>
        <span className="shrink-0 text-foreground tabular-nums">
          {plural(traces, "trace")}
        </span>
        <span className="truncate">· {sureness}</span>
      </span>
    </button>
  );
}
