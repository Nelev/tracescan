"use client";

import { ArrowRight, UserCheck } from "lucide-react";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { getRunOverview } from "@/lib/api";
import {
  type CategoryShare,
  categoryBreakdown,
  failureRate,
  failureTrend,
  largestClusters,
  latestAnalyzed,
  oldestWaiting,
  outcomes,
  runStats,
} from "@/lib/dashboard";
import { formatAge, formatCategory, formatPercent } from "@/lib/format";
import { formatUsage, type RunOverview, totalUsage } from "@/lib/run-overview";
import { formatWhen, plural, RUN_STATUS, runPath, shortId } from "@/lib/runs";
import type { RunRecord, RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CHIP_TONE, TONE_FILL } from "./chip";
import { useResource } from "./use-list";
import { useRuns } from "./use-runs";

const MAX_WAITING = 3;

/**
 * The runs that wait for a person, as one line: how many, the newest few as links, and a button
 * to the newest. The page's one call to action; the table below lists them all.
 */
function NeedsReview({ runs }: { runs: RunRecord[] }) {
  if (runs.length === 0) return null;
  const shown = runs.slice(0, MAX_WAITING);
  const more = runs.length - shown.length;
  const proposals = runs.reduce((sum, r) => sum + r.proposals, 0);
  return (
    <section
      aria-labelledby="needs-review"
      className="type-body flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-card px-3 py-2"
    >
      <h2
        id="needs-review"
        className="type-h3 flex items-center gap-2 text-warning"
      >
        <UserCheck className="size-4" aria-hidden="true" />
        {plural(runs.length, "run")} to review
        <span className="font-normal text-muted-foreground">
          · {plural(proposals, "proposal")}
        </span>
      </h2>
      <ul className="hidden flex-wrap items-center gap-1.5 xl:flex">
        {shown.map((run) => (
          <li key={run.run_id}>
            <Link
              href={runPath(run.run_id)}
              title={`${run.target_app} · ${formatWhen(run.created_at)} · ${plural(run.proposals, "proposal")}`}
              className="flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {shortId(run.run_id)}
              <span className="text-muted-foreground">{run.proposals}</span>
            </Link>
          </li>
        ))}
        {more > 0 && <li className="text-muted-foreground">+{more} more</li>}
      </ul>
      <Link
        href={runPath(runs[0].run_id)}
        className={cn(buttonVariants({ size: "sm" }), "ml-auto")}
      >
        Review newest
      </Link>
    </section>
  );
}
function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border bg-card p-4">
      <span className="type-h4">{label}</span>
      <span className="type-h1 font-mono tabular-nums">{value}</span>
      <span className="type-body text-muted-foreground">{hint}</span>
    </div>
  );
}

function Panel({
  title,
  note,
  children,
  className,
}: {
  title: string;
  note?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const id = `panel-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section
      aria-labelledby={id}
      className={cn(
        "flex min-w-0 flex-col gap-4 rounded-xl border bg-card p-4",
        className,
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id={id}>{title}</h2>
        {note && (
          <span className="type-body text-muted-foreground">{note}</span>
        )}
      </div>
      {children}
    </section>
  );
}

/** Failed traces by category: one hue, bars from a shared baseline, values in text ink. */
function Categories({ shares }: { shares: CategoryShare[] }) {
  const max = Math.max(1, ...shares.map((s) => s.traces));
  return (
    <ul className="type-body flex flex-col gap-3">
      {shares.map((s) => (
        <li key={s.category} className="flex flex-col gap-1.5">
          <span className="flex items-baseline justify-between gap-3">
            <span className="truncate" title={s.category}>
              {formatCategory(s.category)}
            </span>
            <span className="shrink-0 tabular-nums text-muted-foreground">
              {plural(s.traces, "trace")} · {plural(s.clusters, "cluster")}
            </span>
          </span>
          <span className="h-2 bg-track">
            <span
              className={cn(
                "block h-full",
                s.category === "undiagnosed"
                  ? "bg-muted-foreground/50"
                  : "bg-primary",
              )}
              style={{ width: `${(s.traces / max) * 100}%` }}
            />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Failed traces per run, oldest to newest; each bar opens its run and shows its numbers on hover. */
function Trend({ runs }: { runs: RunRecord[] }) {
  const max = Math.max(1, ...runs.map((r) => r.failed_traces));
  return (
    <div className="flex flex-col gap-2">
      <div className="relative flex h-40 items-end gap-1 border-b border-rule">
        <span className="type-h4 absolute top-0 left-0">{max}</span>
        {runs.map((r, i) => (
          <Link
            key={r.run_id}
            href={runPath(r.run_id)}
            className="group relative flex h-full min-w-2 flex-1 items-end justify-center focus-visible:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Run ${shortId(r.run_id)}, ${formatWhen(r.created_at)}: ${plural(r.failed_traces, "failed trace")}, ${plural(r.clusters, "cluster")}`}
          >
            <span
              className="block w-full max-w-6 bg-primary/70 transition-colors group-hover:bg-primary group-focus-visible:bg-primary"
              style={{
                height: `${Math.max(2, (r.failed_traces / max) * 100)}%`,
              }}
            />
            <span
              aria-hidden="true"
              className={cn(
                "type-body pointer-events-none absolute bottom-full z-10 mb-2 flex w-max translate-y-1 flex-col border border-rule bg-popover px-2 py-1 tabular-nums opacity-0 transition-[opacity,translate] duration-150 ease-out group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100",
                // Kept inside the chart at both ends, so it never widens the page.
                i < runs.length / 3 && "left-0",
                i >= (runs.length * 2) / 3 && "right-0",
              )}
            >
              <span className="font-mono">{shortId(r.run_id)}</span>
              <span className="text-muted-foreground">
                {formatWhen(r.created_at)}
              </span>
              <span>
                {plural(r.failed_traces, "failed trace")} ·{" "}
                {plural(r.clusters, "cluster")}
              </span>
            </span>
          </Link>
        ))}
      </div>
      <div className="type-h4 flex justify-between">
        <span>{runs.length > 0 ? formatWhen(runs[0].created_at) : ""}</span>
        <span>
          {runs.length > 0 ? formatWhen(runs[runs.length - 1].created_at) : ""}
        </span>
      </div>
    </div>
  );
}

const OUTCOME_ORDER: RunStatus[] = [
  "completed",
  "review_required",
  "in_progress",
  "failed",
  "aborted",
];

/** How the week's runs ended: one segmented bar, and a legend that names every segment. */
function Outcomes({ counts }: { counts: Record<RunStatus, number> }) {
  const total = OUTCOME_ORDER.reduce((sum, s) => sum + counts[s], 0);
  if (total === 0) {
    return (
      <p className="type-body text-muted-foreground">
        No runs in the last 7 days.
      </p>
    );
  }
  const shown = OUTCOME_ORDER.filter((s) => counts[s] > 0);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex h-3 gap-0.5 overflow-hidden" aria-hidden="true">
        {shown.map((s) => (
          <span
            key={s}
            className={TONE_FILL[RUN_STATUS[s].tone]}
            style={{ width: `${(counts[s] / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="type-body flex flex-wrap gap-2">
        {shown.map((s) => (
          <li
            key={s}
            className={cn(
              "flex items-center gap-2 border px-2.5 py-0.5",
              CHIP_TONE[RUN_STATUS[s].tone],
            )}
          >
            <span
              className={cn("size-2", TONE_FILL[RUN_STATUS[s].tone])}
              aria-hidden="true"
            />
            <span className="text-foreground">{RUN_STATUS[s].label}</span>
            <span className="tabular-nums text-foreground">{counts[s]}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What the newest analyzed run found: its categories and its largest clusters. */
function Latest({ run, overview }: { run: RunRecord; overview: RunOverview }) {
  const shares = categoryBreakdown(overview.clusters);
  const largest = largestClusters(overview.clusters, 5);
  const note = (
    <Link
      href={runPath(run.run_id)}
      className="underline decoration-muted-foreground/60 underline-offset-4 hover:decoration-foreground"
    >
      Run {shortId(run.run_id)}, {formatWhen(run.created_at)}
    </Link>
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="What's breaking" note={note}>
        <Categories shares={shares} />
      </Panel>
      <Panel title="Largest clusters" note={note}>
        <ol className="type-body flex flex-col">
          {largest.map((c) => (
            <li key={c.cluster_id}>
              <Link
                href={runPath(run.run_id, c.cluster_id)}
                className="group -mx-2 flex min-h-11 items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="w-10 shrink-0 text-right font-mono tabular-nums">
                  {c.trace_ids.length}
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-mono" title={c.signature}>
                    {c.signature}
                  </span>
                  <span className="text-muted-foreground">
                    {c.diagnosis?.category ?? "undiagnosed"}
                    {c.diagnosis &&
                      ` · ${formatPercent(c.diagnosis.confidence)} confidence`}
                  </span>
                </span>
                <ArrowRight
                  className="size-4 shrink-0 text-muted-foreground transition-[translate,color] group-hover:translate-x-0.5 group-hover:text-foreground"
                  aria-hidden="true"
                />
              </Link>
            </li>
          ))}
        </ol>
      </Panel>
    </div>
  );
}

/**
 * The landing page: what needs the reader, how failing the target app is, what is breaking and
 * how that changed run to run. Everything is read from the run list and the detail of the newest
 * run that found clusters; nothing here is stored or polled.
 */
export function Dashboard() {
  const recorded = useRuns();
  const runs = recorded.items;
  const loadedAt = recorded.loadedAt ?? 0;
  const latest = latestAnalyzed(runs);
  const detail = useResource(
    (signal) => getRunOverview(latest?.run_id ?? "", signal),
    latest !== null,
    latest?.run_id ?? "",
  );
  const overview =
    latest && detail.value?.summary.run_id === latest.run_id
      ? detail.value
      : null;

  const stats = runStats(runs, loadedAt);
  const waiting = runs.filter((r) => r.status === "review_required");
  const wait = oldestWaiting(runs, loadedAt);
  const rate = overview ? failureRate(overview) : null;
  const trend = failureTrend(runs, 24);
  const spend = overview ? totalUsage(overview.clusters) : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1>Dashboard</h1>
          <p className="type-body text-muted-foreground">
            How the target app is failing, what the agent found, and what waits
            for you.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={recorded.refresh}
          disabled={recorded.status === "loading"}
        >
          Refresh
        </Button>
      </div>

      {recorded.status === "error" && (
        <p role="alert" className="type-body text-destructive">
          Could not load the runs. Check that the backend is running, then
          refresh.
        </p>
      )}

      <NeedsReview runs={waiting} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile
          label="Failure rate"
          value={rate === null ? "—" : formatPercent(rate)}
          hint={
            overview
              ? `${overview.summary.failed_traces} of ${plural(overview.summary.traces, "trace")}, latest run`
              : "no run has judged traces yet"
          }
        />
        <Tile
          label="Failures found"
          value={String(stats.failures)}
          hint={`failed traces in ${plural(stats.runs, "run")}, 7 days`}
        />
        <Tile
          label="Open proposals"
          value={String(stats.openProposals)}
          hint={`in ${plural(stats.awaiting, "run")} awaiting review`}
        />
        <Tile
          label="Oldest waiting"
          value={wait === null ? "—" : formatAge(wait)}
          hint={
            wait === null
              ? "nothing waits for you"
              : "since a run stopped for review"
          }
        />
      </div>

      {latest && overview && <Latest run={latest} overview={overview} />}
      {latest && !overview && detail.status === "loading" && (
        <p className="type-body text-muted-foreground">
          Loading the latest run…
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Panel
          title="Failed traces per run"
          note={
            trend.length > 0 ? `last ${plural(trend.length, "run")}` : undefined
          }
        >
          {trend.length === 0 ? (
            <p className="type-body text-muted-foreground">
              No run has finished judging yet. Start one with New run.
            </p>
          ) : (
            <Trend runs={trend} />
          )}
        </Panel>
        <div className="flex flex-col gap-4">
          <Panel title="Run outcomes" note="last 7 days">
            <Outcomes counts={outcomes(runs, loadedAt)} />
          </Panel>
          {spend && spend.calls > 0 && (
            <Panel title="Diagnosis spend" note="latest run">
              <p className="type-body">{formatUsage(spend)}</p>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
