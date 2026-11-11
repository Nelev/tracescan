"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { formatDuration } from "@/lib/format";
import { formatWhen, shortId } from "@/lib/runs";
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
import { useTraceList } from "./use-traces";

const COLUMNS = [
  { label: "Started" },
  { label: "Verdict" },
  { label: "Duration", numeric: true },
  { label: "Spans", numeric: true },
  { label: "Lowest score", numeric: true },
  { label: "Failing span" },
  { label: "Why" },
  { label: "Trace" },
];

function Row({ trace }: { trace: TraceRow }) {
  const router = useRouter();
  const { label, tone } = traceVerdict(trace);
  const why = trace.error_type ?? trace.failing_check;
  return (
    <tr
      className="cursor-pointer border-t hover:bg-foreground/5"
      onClick={() => router.push(tracePath(trace.trace_id))}
    >
      <td className={CELL}>
        <time dateTime={trace.start_time}>{formatWhen(trace.start_time)}</time>
      </td>
      <td className={CELL}>
        <Chip tone={tone} size="sm">
          {label}
        </Chip>
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
  const { status, items: traces } = stored;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1>Traces</h1>
          <p className="type-body text-muted-foreground">
            The spans the target app sent to the collector, newest first.
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
      <div className="overflow-x-auto rounded-xl border bg-card">
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
                <Row key={trace.trace_id} trace={trace} />
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
