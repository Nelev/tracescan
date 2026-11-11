"use client";

import { ArrowLeft, RotateCw, UserCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { getRunOverview } from "@/lib/api";
import { tally, tallyText } from "@/lib/review";
import {
  emptyOverview,
  formatUsage,
  pipeline,
  type RunOverview,
  totalUsage,
} from "@/lib/run-overview";
import { plural, RUN_STATUS, type StatusTone, shortId } from "@/lib/runs";
import { cn } from "@/lib/utils";
import { AgentConsole } from "./agent-console";
import { Chip } from "./chip";
import { ClusterCard, type LiveDiagnosis } from "./cluster-card";
import { PipelineStepper } from "./pipeline-stepper";
import { type RunStream, useRun } from "./run-stream";
import { useResource } from "./use-list";
import { useReview } from "./use-review";

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  return `${mm}:${String(total % 60).padStart(2, "0")}`;
}

/** The clock ticks here, in a leaf, so the page is not re-rendered every second. */
function Elapsed({
  startedAt,
  endedAt,
}: {
  startedAt: number;
  endedAt: number | null;
}) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (endedAt !== null) return;
    const id = setInterval(() => setNow(performance.now()), 1000);
    return () => clearInterval(id);
  }, [endedAt]);
  return (
    <span className="type-h4 tabular-nums">
      {formatElapsed((endedAt ?? now) - startedAt)}
    </span>
  );
}

/** The run's status, from this window's stream while it has the newer word, else the server's. */
function statusOf(
  overview: RunOverview | null,
  stream: RunStream | null,
): { label: string; tone: StatusTone } | null {
  if (stream?.phase === "running") return { label: "Running", tone: "info" };
  if (stream?.phase === "cancelled")
    return { label: "Cancelled", tone: "stopped" };
  if (stream?.phase === "lost")
    return { label: "Connection lost", tone: "destructive" };
  return overview ? RUN_STATUS[overview.status] : null;
}

/** Why a run shows no clusters, in a sentence. */
function noClusters(overview: RunOverview, streaming: boolean): string {
  if (streaming)
    return "Clusters appear here once the failed traces are grouped.";
  if (overview.status === "completed") {
    return overview.summary.failed_traces === 0
      ? "The judge found no failed trace in this window: nothing to triage."
      : "This run found no clusters.";
  }
  if (overview.status === "in_progress") {
    return "No clusters yet. This run is not streaming in this window: refresh to see where it stands.";
  }
  return "This run ended before it found any clusters.";
}

/**
 * One run, live or finished: where it stands in the pipeline, what it found cluster by cluster
 * (with the evidence as span trees), the review of its proposals while it waits for one, and the
 * agent console beside it. The checkpoint is read again whenever this window's stream says a node
 * ended, when the stream ends, after a review, and on Refresh.
 */
export function RunView({
  runId,
  focusCluster,
}: {
  runId: string;
  /** A cluster to open and scroll to, when the page was linked to it (a trace's cluster). */
  focusCluster: string | null;
}) {
  const run = useRun();
  const stream = run.runId === runId ? run : null;
  // This window's stream, while it is still running: the stepper and the cards follow it.
  const live = stream?.phase === "running" ? stream.live : null;
  const streaming = live !== null;
  // Refresh reloads the detail and the proposals; a taken review reloads only the detail, so
  // the review's outcome stays on screen.
  const [refreshes, setRefreshes] = useState(0);
  const [reviews, setReviews] = useState(0);

  const detail = useResource(
    (signal) => getRunOverview(runId, signal),
    true,
    `${stream?.live.checkpoints ?? 0}:${stream?.phase ?? ""}:${refreshes}:${reviews}`,
  );
  // A run streaming in this window may not have a checkpoint to read yet.
  const overview = detail.value ?? (streaming ? emptyOverview(runId) : null);
  const waiting = overview?.status === "review_required" && !streaming;

  // Loaded with the detail, not after it, so a waiting run shows its pickers at once; again on
  // Refresh and after a review, like the detail.
  const review = useReview(runId, !streaming, String(refreshes), (id) => {
    run.markReviewed(id);
    setReviews((n) => n + 1);
  });
  const proposals = new Map(
    (review.state.step === "open" || review.state.step === "reviewed"
      ? review.state.detail.proposals
      : []
    ).map((p) => [p.cluster_id, p]),
  );
  const sending = review.state.step === "open" && review.state.sending;
  // Both reads must agree that the run waits: they are loaded side by side.
  const decidable =
    waiting &&
    review.state.step === "open" &&
    review.state.detail.status === "review_required";

  const status = statusOf(detail.value, stream);
  const clusters = overview?.clusters ?? [];
  const usage = totalUsage(clusters);

  function liveDiagnosis(clusterId: string): LiveDiagnosis {
    if (live === null) return null;
    const state = live.diagnoses[clusterId];
    if (state === undefined) return "queued";
    return state === "running" ? "diagnosing" : null;
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Link
          href="/runs"
          className={cn(buttonVariants({ variant: "ghost" }), "-ml-2.5 w-fit")}
        >
          <ArrowLeft aria-hidden="true" />
          All runs
        </Link>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="font-mono" title={runId}>
            Run {shortId(runId)}
          </h1>
          {status && (
            <output>
              <Chip tone={status.tone} live={streaming}>
                {status.label}
              </Chip>
            </output>
          )}
          {stream?.startedAt != null && (
            <Elapsed startedAt={stream.startedAt} endedAt={stream.endedAt} />
          )}
          {usage.calls > 0 && (
            <span className="type-body text-muted-foreground">
              Diagnoses: {formatUsage(usage)}
            </span>
          )}
          <span className="ml-auto flex gap-2">
            {streaming ? (
              <Button variant="outline" onClick={run.cancel}>
                Cancel run
              </Button>
            ) : (
              <Button
                variant="outline"
                onClick={() => setRefreshes((n) => n + 1)}
                disabled={detail.status === "loading"}
              >
                <RotateCw aria-hidden="true" />
                Refresh
              </Button>
            )}
          </span>
        </div>
      </div>

      {detail.status === "error" && !streaming && (
        <p role="alert" className="type-body text-destructive">
          {detail.missing
            ? "The server does not know this run."
            : "Could not load the run. Check that the backend is running, then refresh."}
        </p>
      )}
      {detail.status === "loading" && overview === null && (
        <p className="type-body text-muted-foreground">Loading run…</p>
      )}

      {overview && (
        <>
          <section className="rounded-xl border bg-card p-4">
            <h2 className="sr-only">Pipeline</h2>
            <PipelineStepper stages={pipeline(overview, live)} />
          </section>

          <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
            <section
              aria-labelledby="findings"
              className="flex min-w-0 flex-col gap-3"
            >
              <h2 id="findings" className="flex items-baseline gap-2">
                Findings
                <span className="type-body text-muted-foreground">
                  {clusters.length > 0 &&
                    `${plural(clusters.length, "cluster")} of ${plural(overview.summary.failed_traces, "failed trace")}`}
                </span>
              </h2>
              {review.state.step === "unavailable" && (
                <div className="flex flex-wrap items-center gap-3">
                  <p role="alert" className="type-body text-destructive">
                    {review.state.problem}
                  </p>
                  <Button variant="outline" size="sm" onClick={review.reload}>
                    Try again
                  </Button>
                </div>
              )}
              {review.state.step === "reviewed" && (
                <output className="type-body flex flex-col gap-1 rounded-xl border border-success/35 bg-success/5 p-4">
                  <span className="text-success">
                    Review recorded:{" "}
                    {tallyText(
                      tally(review.state.detail.proposals, review.decisions),
                    )}
                  </span>
                  {review.state.result.actionsLog.length === 0 ? (
                    <span className="text-muted-foreground">
                      Nothing was written.
                    </span>
                  ) : (
                    <ul className="font-mono text-muted-foreground [overflow-wrap:anywhere]">
                      {review.state.result.actionsLog.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  )}
                </output>
              )}
              {clusters.length === 0 ? (
                <p className="type-body rounded-xl border border-dashed p-4 text-muted-foreground">
                  {noClusters(overview, streaming)}
                </p>
              ) : (
                clusters.map((cluster) => (
                  <ClusterCard
                    key={cluster.cluster_id}
                    cluster={cluster}
                    focused={cluster.cluster_id === focusCluster}
                    live={liveDiagnosis(cluster.cluster_id)}
                    proposal={proposals.get(cluster.cluster_id) ?? null}
                    decision={
                      decidable
                        ? review.decisions[cluster.cluster_id]
                        : (cluster.decision ?? undefined)
                    }
                    onDecide={
                      decidable
                        ? (d) => review.decide(cluster.cluster_id, d)
                        : null
                    }
                    deciding={sending}
                  />
                ))
              )}
              {review.state.step === "open" && decidable && (
                <ReviewBar
                  progress={tally(
                    review.state.detail.proposals,
                    review.decisions,
                  )}
                  problem={review.state.problem}
                  sending={sending}
                  onSubmit={() => void review.submit()}
                  onReload={review.reload}
                />
              )}
            </section>
            {/* Beside the findings on a wide screen, above them otherwise: a live run is read there. */}
            <div
              className={cn(
                "order-first xl:sticky xl:top-20 xl:order-none",
                stream && "h-80 xl:h-[calc(100vh-6.5rem)]",
              )}
            >
              <AgentConsole runId={runId} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** The review's sticky bar: how many proposals are decided, and one send for all of them. */
function ReviewBar({
  progress,
  problem,
  sending,
  onSubmit,
  onReload,
}: {
  progress: ReturnType<typeof tally>;
  problem: string | null;
  sending: boolean;
  onSubmit: () => void;
  onReload: () => void;
}) {
  return (
    <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 border border-rule bg-popover px-4 py-3">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="type-h3 flex items-center gap-2">
          <UserCheck
            className={cn(
              "size-4",
              progress.complete ? "text-success" : "text-warning",
            )}
            aria-hidden="true"
          />
          Review
          <span className="font-normal text-muted-foreground tabular-nums">
            {tallyText(progress)}
          </span>
        </span>
        {problem && (
          <p role="alert" className="type-body text-destructive">
            {problem}
          </p>
        )}
      </div>
      <div className="flex gap-2">
        {problem && (
          <Button variant="outline" onClick={onReload} disabled={sending}>
            Reload run
          </Button>
        )}
        <Button onClick={onSubmit} disabled={!progress.complete || sending}>
          {sending ? "Sending…" : "Submit decisions"}
        </Button>
      </div>
    </div>
  );
}
