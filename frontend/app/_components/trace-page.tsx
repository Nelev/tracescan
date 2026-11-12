"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { INDEXED_RUNS } from "@/lib/clusters";
import { formatDuration } from "@/lib/format";
import { formatWhen, shortId } from "@/lib/runs";
import { formatScore, traceVerdict, waterfall } from "@/lib/traces";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import { TraceTree, TreeLegend } from "./trace-tree";
import { ClusterLink } from "./traces-list";
import { useClusterIndex, useTrace } from "./use-traces";

/** The clusters the trace landed in, over the newest analyzed runs, each opening on its run. */
function Clusters({ traceId }: { traceId: string }) {
  const index = useClusterIndex();
  const memberships = index.value?.get(traceId) ?? [];
  return (
    <section
      aria-labelledby="trace-clusters"
      className="type-body flex flex-wrap items-center gap-x-3 gap-y-2"
    >
      <h2 id="trace-clusters" className="type-h4">
        Clusters
      </h2>
      {index.value === null ? (
        <span className="text-muted-foreground">
          {index.status === "error" ? "Could not read the runs." : "Loading…"}
        </span>
      ) : memberships.length === 0 ? (
        <span className="text-muted-foreground">
          In no cluster of the last {INDEXED_RUNS} analyzed runs: it passed, or
          was not in their window.
        </span>
      ) : (
        <ul className="flex flex-wrap items-center gap-2">
          {memberships.map((m) => (
            <li
              key={`${m.runId}:${m.clusterId}`}
              className="flex items-center gap-1.5"
            >
              <ClusterLink membership={m} />
              <span className="text-muted-foreground">
                run {shortId(m.runId)}, {formatWhen(m.createdAt)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

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
              <span className="text-foreground">{trace.app}</span> ·{" "}
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
      {trace && <Clusters traceId={traceId} />}
      {trace && (
        <>
          <TreeLegend />
          <div className="flex min-h-[28rem] flex-1 flex-col overflow-hidden surface rounded-xl border lg:h-[calc(100dvh-16rem)] lg:flex-none">
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
