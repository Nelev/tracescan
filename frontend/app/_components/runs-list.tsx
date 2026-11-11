"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  formatWhen,
  formatWindow,
  RUN_STATUS,
  runDuration,
  runPath,
  shortId,
} from "@/lib/runs";
import type { RunRecord } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import { CELL, HEAD, LINK, NUMERIC } from "./styles";
import { listFooter } from "./use-list";
import { useRuns } from "./use-runs";

/** The run's funnel: failed traces, then clusters, then proposals. */
function Funnel({ run }: { run: RunRecord }) {
  const steps = [
    { n: run.failed_traces, label: "failed traces" },
    { n: run.clusters, label: "clusters" },
    { n: run.proposals, label: "proposals" },
  ];
  return (
    <span className="flex items-center gap-1.5 tabular-nums">
      <span className="sr-only">
        {steps.map((s) => `${s.n} ${s.label}`).join(", ")}
      </span>
      {steps.map((s, i) => (
        <span
          key={s.label}
          className="flex items-center gap-1.5"
          aria-hidden="true"
        >
          {i > 0 && <ArrowRight className="size-3 text-muted-foreground" />}
          <span className={cn(s.n === 0 && "text-muted-foreground")}>
            {s.n}
          </span>
        </span>
      ))}
    </span>
  );
}

const COLUMNS = [
  { label: "Started" },
  { label: "Status" },
  { label: "App" },
  { label: "Window" },
  { label: "Failed → clusters → proposals" },
  { label: "Duration", numeric: true },
  { label: "Started by" },
  { label: "Run" },
];

function Row({ run }: { run: RunRecord }) {
  const router = useRouter();
  const { label, tone } = RUN_STATUS[run.status];
  return (
    <tr
      className="cursor-pointer border-t hover:bg-foreground/5"
      onClick={() => router.push(runPath(run.run_id))}
    >
      <td className={CELL}>
        <time dateTime={run.created_at}>{formatWhen(run.created_at)}</time>
      </td>
      <td className={CELL}>
        <Chip tone={tone} size="sm" live={run.status === "in_progress"}>
          {label}
        </Chip>
      </td>
      <td className={CELL}>{run.target_app}</td>
      <td className={cn(CELL, "text-muted-foreground")}>
        {formatWindow(run.since, run.until)}
      </td>
      <td className={CELL}>
        <Funnel run={run} />
      </td>
      <td className={cn(CELL, NUMERIC, "text-muted-foreground")}>
        {runDuration(run) ?? "—"}
      </td>
      <td className={cn(CELL, !run.started_by && "text-muted-foreground")}>
        {run.started_by ?? "Unknown"}
      </td>
      <td className={CELL}>
        <Link
          href={runPath(run.run_id)}
          title={run.run_id}
          className={LINK}
          onClick={(e) => e.stopPropagation()}
        >
          {shortId(run.run_id)}
        </Link>
      </td>
    </tr>
  );
}

/**
 * Every recorded run, newest first, each opening its page. The list loads
 * when the page opens, again when this window's run changes phase or gets its first event (the
 * server records a run once it accepts it), once more a moment after a cancel or a lost
 * connection (the server records `aborted` only when it notices), and on Refresh; no polling.
 */
export function RunsList() {
  const recorded = useRuns();
  const runs = recorded.items;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1>Runs</h1>
          <p className="type-body text-muted-foreground">
            Each run judges the window's traces, clusters the failures,
            diagnoses each cluster and drafts an issue for you to approve.
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

      <section className="flex flex-col gap-3">
        <h2 className="sr-only">All runs</h2>
        <div className="overflow-x-auto rounded-xl border bg-card">
          {recorded.status === "error" && (
            <p role="alert" className="type-body px-4 pt-4 text-destructive">
              Could not load the runs. Check that the backend is running, then
              refresh.
            </p>
          )}
          {runs.length === 0 ? (
            recorded.status !== "error" && (
              <p className="type-body p-4 text-muted-foreground">
                {recorded.status === "loading"
                  ? "Loading runs…"
                  : "No runs yet. Start one with New run."}
              </p>
            )
          ) : (
            <table className="type-body w-full border-collapse text-left">
              <caption className="sr-only">Recorded runs, newest first</caption>
              <thead className={HEAD}>
                <tr>
                  {COLUMNS.map(({ label, numeric }) => (
                    <th
                      key={label}
                      scope="col"
                      className={cn(
                        "type-h4",
                        CELL,
                        "py-3",
                        numeric && NUMERIC,
                      )}
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <Row key={r.run_id} run={r} />
                ))}
              </tbody>
            </table>
          )}
        </div>
        <p className="type-h4">{listFooter(recorded, "run")}</p>
      </section>
    </div>
  );
}
