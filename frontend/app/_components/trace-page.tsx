"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { formatDuration } from "@/lib/format";
import { formatWhen } from "@/lib/runs";
import { formatScore, traceVerdict, waterfall } from "@/lib/traces";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import { TraceTree, TreeLegend } from "./trace-tree";
import { useTrace } from "./use-traces";

/** One stored trace on a page of its own, opened on `spanId` when one is given. */
export function TracePage({
  traceId,
  spanId,
}: {
  traceId: string;
  spanId: string | null;
}) {
  const state = useTrace(traceId);
  const trace = state.value;
  const rows = trace ? waterfall(trace.tree) : [];
  const verdict = trace ? traceVerdict(trace) : null;
  return (
    <div className="flex min-h-[32rem] flex-1 flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Link
          href="/traces"
          className={cn(buttonVariants({ variant: "ghost" }), "-ml-2.5 w-fit")}
        >
          <ArrowLeft aria-hidden="true" />
          All traces
        </Link>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="font-mono [overflow-wrap:anywhere]">{traceId}</h1>
          {verdict && (
            <Chip tone={verdict.tone} size="sm">
              {verdict.label}
            </Chip>
          )}
        </div>
        {trace && (
          <div className="type-body flex flex-wrap items-center gap-x-4 gap-y-2 text-muted-foreground">
            <span>
              {formatWhen(trace.tree.start_time)} ·{" "}
              {formatDuration(rows[0].durationMs)} · {rows.length}{" "}
              {rows.length === 1 ? "span" : "spans"}
            </span>
            {trace.scores.map((s) => (
              <span
                key={s.evaluator}
                className={cn(
                  "rounded-md border px-2 font-mono",
                  s.failed && "border-destructive/40 text-destructive",
                )}
              >
                {s.evaluator} {formatScore(s.value)}
              </span>
            ))}
          </div>
        )}
      </div>
      {state.status === "loading" && trace === null && (
        <p className="type-body text-muted-foreground">Loading trace…</p>
      )}
      {state.status === "error" && (
        <p role="alert" className="type-body text-destructive">
          {state.missing
            ? "The server has no whole trace by this id: unknown, of another app, or still missing spans."
            : "Could not load the trace. Check that the backend is running, then try again."}
        </p>
      )}
      {trace && (
        <>
          <TreeLegend />
          <div className="flex min-h-[28rem] flex-1 flex-col overflow-hidden rounded-xl border bg-card lg:h-[calc(100vh-16rem)] lg:flex-none">
            <TraceTree
              key={`${traceId}:${spanId}`}
              trace={trace}
              initialSpan={spanId}
              layout="split"
            />
          </div>
        </>
      )}
    </div>
  );
}
