"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { INDEXED_RUNS, type Membership } from "@/lib/clusters";
import { formatDuration } from "@/lib/format";
import { formatWhen, runPath, shortId } from "@/lib/runs";
import {
  formatScore,
  type TraceRow,
  tracePath,
  traceVerdict,
} from "@/lib/traces";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import { CELL, HEAD, LINK, NUMERIC } from "./styles";
import { listFooter } from "./use-list";
import { useClusterIndex, useTraceList } from "./use-traces";

const COLUMNS = [
  { label: "Started" },
  { label: "App" },
  { label: "Verdict" },
  { label: "Cluster" },
  { label: "Duration", numeric: true },
  { label: "Spans", numeric: true },
  { label: "Lowest score", numeric: true },
  { label: "Failing span" },
  { label: "Why" },
  { label: "Trace" },
];

/** One cluster a trace is in, as a link that opens that cluster on its run's page. */
export function ClusterLink({ membership: m }: { membership: Membership }) {
  return (
    <Link
      href={runPath(m.runId, m.clusterId)}
      title={`${m.signature} · run ${shortId(m.runId)}, ${formatWhen(m.createdAt)}`}
      className="inline-flex items-baseline gap-1.5 rounded-md border px-2 hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      onClick={(e) => e.stopPropagation()}
    >
      <span className="font-mono">{m.clusterId}</span>
      <span className="text-muted-foreground">
        {m.category ?? "undiagnosed"}
      </span>
    </Link>
  );
}

function Row({
  trace,
  clusters,
}: {
  trace: TraceRow;
  /** Its clusters, newest run first; undefined while the index loads or when it failed. */
  clusters: Membership[] | null | undefined;
}) {
  const router = useRouter();
  const { label, tone } = traceVerdict(trace);
  const why = trace.error_type ?? trace.failing_check;
  return (
    <tr
      className="cursor-pointer border-t hover:bg-hover"
      onClick={() => router.push(tracePath(trace.trace_id))}
    >
      <td className={CELL}>
        <time dateTime={trace.start_time}>{formatWhen(trace.start_time)}</time>
      </td>
      <td className={cn(CELL, "text-muted-foreground")}>{trace.app}</td>
      <td className={CELL}>
        <Chip tone={tone} size="sm">
          {label}
        </Chip>
      </td>
      <td className={CELL}>
        {clusters === undefined ? (
          <span className="text-muted-foreground">…</span>
        ) : clusters === null || clusters.length === 0 ? (
          ""
        ) : (
          <span className="flex items-center gap-1.5">
            <ClusterLink membership={clusters[0]} />
            {clusters.length > 1 && (
              <span
                className="text-muted-foreground"
                title="In earlier runs too"
              >
                +{clusters.length - 1}
              </span>
            )}
          </span>
        )}
      </td>
      <td className={cn(CELL, NUMERIC)}>{formatDuration(trace.duration_ms)}</td>
      <td className={cn(CELL, NUMERIC)}>{trace.spans}</td>
      <td className={cn(CELL, NUMERIC)}>{formatScore(trace.min_score)}</td>
      <td className={cn(CELL, "font-mono")}>{trace.failing_span_name ?? ""}</td>
      <td className={cn(CELL, "font-mono text-muted-foreground")}>
        {why ?? ""}
      </td>
      <td className={CELL}>
        <Link
          href={tracePath(trace.trace_id)}
          className={LINK}
          title={trace.trace_id}
          onClick={(e) => e.stopPropagation()}
        >
          {shortId(trace.trace_id)}
        </Link>
      </td>
    </tr>
  );
}

/**
 * The trace store, read-only: the newest traces (up to 200) with the verdict their scores give.
 * Loaded when the page opens, when the filter changes, and on Refresh; no polling.
 */
export function TracesList() {
  const [failedOnly, setFailedOnly] = useState(false);
  const stored = useTraceList(true, failedOnly);
  const index = useClusterIndex();
  // Undefined while the index loads; null when it could not be read (the column stays empty).
  const clustersOf = (traceId: string) =>
    index.value
      ? (index.value.get(traceId) ?? [])
      : index.status === "error"
        ? null
        : undefined;
  const { status, items: traces } = stored;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1>Traces</h1>
          <p className="type-body text-muted-foreground">
            The traces the target apps sent to the collector, newest first, with
            the cluster each one landed in over the last {INDEXED_RUNS} analyzed
            runs.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant={failedOnly ? "secondary" : "outline"}
            aria-pressed={failedOnly}
            onClick={() => setFailedOnly((on) => !on)}
          >
            Failed only
          </Button>
          <Button
            variant="outline"
            onClick={stored.refresh}
            disabled={status === "loading"}
          >
            Refresh
          </Button>
        </div>
      </div>
      <div className="relative overflow-x-auto rounded-xl border bg-card">
        {status === "error" && (
          <p role="alert" className="type-body px-4 pt-4 text-destructive">
            Could not load the traces. Check that the backend is running, then
            refresh.
          </p>
        )}
        {traces.length === 0 ? (
          status !== "error" && (
            <p className="type-body p-4 text-muted-foreground">
              {status === "loading"
                ? "Loading traces…"
                : failedOnly
                  ? "No failed traces stored."
                  : "No traces stored yet. Point an instrumented app at /v1/traces."}
            </p>
          )
        ) : (
          <table className="type-body w-full border-collapse text-left">
            <caption className="sr-only">Stored traces, newest first</caption>
            <thead className={HEAD}>
              <tr>
                {COLUMNS.map(({ label, numeric }) => (
                  <th
                    key={label}
                    scope="col"
                    className={cn("type-h4", CELL, "py-3", numeric && NUMERIC)}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {traces.map((trace) => (
                <Row
                  key={trace.trace_id}
                  trace={trace}
                  clusters={clustersOf(trace.trace_id)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="type-h4">
        {listFooter(stored, failedOnly ? "failed trace" : "trace")}
      </p>
    </div>
  );
}
