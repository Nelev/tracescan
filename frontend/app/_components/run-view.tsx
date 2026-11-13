"use client";

import {
  Activity,
  ArrowLeft,
  ListChecks,
  Play,
  RotateCw,
  UserCheck,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { getRunOverview } from "@/lib/api";
import { tally, tallyText } from "@/lib/review";
import {
  emptyOverview,
  formatUsage,
  pipeline,
  type RunOverview,
  reachedTraceLimit,
  totalUsage,
} from "@/lib/run-overview";
import { plural, RUN_STATUS, type StatusTone, shortId } from "@/lib/runs";
import { MAX_JUDGED_TRACES } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import type { LiveDiagnosis } from "./cluster-card";
import { ClusterMapPanel } from "./cluster-map-panel";
import { FindingsBrowser } from "./findings-browser";
import { PipelineStepper } from "./pipeline-stepper";
import { type RunStream, useRun } from "./run-stream";
import { TypingDots } from "./typing-dots";
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
    return { label: "Stopped", tone: "stopped" };
  if (stream?.phase === "lost")
    return { label: "Connection lost", tone: "destructive" };
  return overview ? RUN_STATUS[overview.status] : null;
}

/** The run page's two views: the live map and console, and the findings to read and review. */
type RunTab = "activity" | "findings";

/** Why the map tab shows no map, in a sentence. */
function noMap(overview: RunOverview, streaming: boolean): string {
  if (streaming) return "The map appears once the failed traces are clustered.";
  if (overview.clusters.length === 0) return noClusters(overview, false);
  return "No cluster map: the run had too few failed traces to embed, or was clustered before the map existed.";
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
  // The graph has paused at the review, though the stream still sends the proposals and their UI
  // specs: the run already waits for a person, so it reads as waiting and takes decisions.
  const paused = live?.nodes.human_review === "paused";
  const streaming = live !== null && !paused;
  // Refresh reloads the detail and the proposals; a taken review reloads only the detail, so
  // the review's outcome stays on screen.
  const [refreshes, setRefreshes] = useState(0);
  const [reviews, setReviews] = useState(0);
  // The cluster picked on the map, and the card to open: both start on a linked cluster.
  const [mapCluster, setMapCluster] = useState(focusCluster);
  // A new `ask` each time, so opening the same finding again scrolls to it again.
  const [finding, setFinding] = useState(
    focusCluster === null ? null : { clusterId: focusCluster, ask: 0 },
  );
  // A run streaming in this window opens on its map and console; any other, or a page linked to
  // a cluster, opens on its findings.
  const [tab, setTab] = useState<RunTab>(
    focusCluster === null && streaming ? "activity" : "findings",
  );

  function openFinding(clusterId: string) {
    setTab("findings");
    setFinding((f) => ({ clusterId, ask: (f?.ask ?? 0) + 1 }));
  }

  const detail = useResource(
    (signal) => getRunOverview(runId, signal),
    true,
    `${stream?.live.checkpoints ?? 0}:${stream?.phase ?? ""}:${paused}:${refreshes}:${reviews}`,
    // A stream that was stopped or lost: the server records the run as stopped (and resumable)
    // only once it has seen the connection close, so read it again a moment later.
    stream?.phase === "cancelled" || stream?.phase === "lost",
  );
  // A run streaming in this window may not have a checkpoint to read yet.
  const overview =
    detail.value ?? (live !== null ? emptyOverview(runId) : null);
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

  const progress =
    decidable && review.state.step === "open"
      ? tally(review.state.detail.proposals, review.decisions)
      : null;
  const toDecide = progress
    ? progress.total - progress.approved - progress.rejected
    : 0;
  const status = paused
    ? RUN_STATUS.review_required
    : statusOf(detail.value, stream);
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
            {overview?.resumable && run.phase !== "running" && (
              // It stopped with steps left: go on from its last checkpoint, in this window.
              <Button onClick={() => run.resume(runId)}>
                <Play aria-hidden="true" />
                Resume run
              </Button>
            )}
            {streaming ? (
              <Button variant="outline" onClick={run.cancel}>
                Stop run
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
          <section className="surface flex flex-col gap-3 rounded-xl border p-4">
            <h2 className="sr-only">Pipeline</h2>
            <PipelineStepper stages={pipeline(overview, live)} />
            {reachedTraceLimit(overview.summary) ? (
              <p className="type-body text-muted-foreground">
                This run reached the limit of {MAX_JUDGED_TRACES} traces: it
                judged the newest {MAX_JUDGED_TRACES} in its window, so any
                older ones were not judged. To cover them, run a window that
                ends earlier.
              </p>
            ) : null}
          </section>

          <Tabs value={tab} onValueChange={(value) => setTab(value as RunTab)}>
            <TabsList aria-label="Run views">
              <TabsTab value="activity">
                <Activity className="size-4" aria-hidden="true" />
                Map
                {streaming && <TypingDots label="(the run is streaming)" />}
              </TabsTab>
              <TabsTab value="findings">
                <ListChecks className="size-4" aria-hidden="true" />
                Findings
                <span className="type-body rounded-full bg-secondary px-2 tabular-nums text-secondary-foreground">
                  {clusters.length}
                </span>
                {/* On a phone the review bar carries the count, and the tab row stays one line. */}
                {toDecide > 0 && (
                  <span className="hidden sm:inline-flex">
                    <Chip tone="warning" size="sm">
                      {toDecide} to decide
                    </Chip>
                  </span>
                )}
              </TabsTab>
            </TabsList>

            {/* Both panels stay mounted, so the map keeps its view and the console its place. */}
            <TabsPanel value="activity" keepMounted>
              <div className="min-w-0">
                {overview.cluster_map && clusters.length > 0 ? (
                  <ClusterMapPanel
                    map={overview.cluster_map}
                    clusters={clusters}
                    selected={mapCluster}
                    onSelect={setMapCluster}
                    onOpenFinding={openFinding}
                  />
                ) : (
                  <p className="type-body rounded-xl border border-dashed p-4 text-muted-foreground">
                    {noMap(overview, streaming)}
                  </p>
                )}
              </div>
            </TabsPanel>

            <TabsPanel value="findings" keepMounted>
              <section
                aria-labelledby="findings"
                className="flex min-w-0 flex-col gap-4"
              >
                {/* The tab already says "Findings": the heading is for screen readers, one line says the rest. */}
                <h2 id="findings" className="sr-only">
                  Findings
                </h2>
                {clusters.length > 0 && (
                  <p className="type-body max-w-prose text-muted-foreground">
                    {plural(overview.summary.failed_traces, "failed trace")}{" "}
                    grouped by cause into {plural(clusters.length, "finding")}.
                    {decidable &&
                      (clusters.length === 1
                        ? " Approve it if it is worth an issue, then submit."
                        : " Approve the ones worth an issue, then submit.")}
                  </p>
                )}
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
                  <FindingsBrowser
                    clusters={clusters}
                    ask={finding}
                    proposals={proposals}
                    decisionOf={(c) =>
                      decidable
                        ? review.decisions[c.cluster_id]
                        : (c.decision ?? undefined)
                    }
                    deciding={decidable}
                    onDecide={decidable ? review.decide : null}
                    sending={sending}
                    live={liveDiagnosis}
                  />
                )}
                {progress && review.state.step === "open" && (
                  <ReviewBar
                    progress={progress}
                    problem={review.state.problem}
                    sending={sending}
                    onSubmit={() => void review.submit()}
                    onReload={review.reload}
                    clearDock={run.runId !== null}
                  />
                )}
              </section>
            </TabsPanel>
          </Tabs>
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
  clearDock,
}: {
  progress: ReturnType<typeof tally>;
  problem: string | null;
  sending: boolean;
  onSubmit: () => void;
  onReload: () => void;
  /** This window has a run, so the console's launcher sits in the corner: keep Submit clear of it. */
  clearDock: boolean;
}) {
  return (
    <div
      className={cn(
        "sticky bottom-4 z-sticky flex flex-wrap items-center justify-between gap-3 rounded-xl border surface-raised px-4 py-3",
        clearDock && "mr-(--dock-clear)",
      )}
    >
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
