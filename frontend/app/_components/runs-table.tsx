import { Button } from "@/components/ui/button";
import { formatWhen, formatWindow, RUN_STATUS, shortId } from "@/lib/runs";
import type { RunRecord } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import { PANE_HEIGHT } from "./console-styles";
import type { RunsState } from "./use-runs";

const COLUMNS = [
  { label: "Started" },
  { label: "App" },
  { label: "Window" },
  { label: "Status" },
  { label: "Failures", numeric: true },
  { label: "Clusters", numeric: true },
  { label: "Proposals", numeric: true },
  { label: "Started by" },
  { label: "Run" },
  { label: "Review" },
];

const CELL = "px-4 py-2 whitespace-nowrap";
const NUMERIC = "text-right tabular-nums";

function Row({
  run,
  onReview,
}: {
  run: RunRecord;
  onReview: (runId: string) => void;
}) {
  const { label, tone } = RUN_STATUS[run.status];
  return (
    <tr className="border-t">
      <td className={CELL}>
        <time dateTime={run.created_at}>{formatWhen(run.created_at)}</time>
      </td>
      <td className={CELL}>{run.target_app}</td>
      <td className={cn(CELL, "text-muted-foreground")}>
        {formatWindow(run.since, run.until)}
      </td>
      <td className={CELL}>
        <Chip tone={tone} size="sm">
          {label}
        </Chip>
      </td>
      <td className={cn(CELL, NUMERIC)}>{run.failed_traces}</td>
      <td className={cn(CELL, NUMERIC)}>{run.clusters}</td>
      <td className={cn(CELL, NUMERIC)}>{run.proposals}</td>
      <td className={cn(CELL, !run.started_by && "text-muted-foreground")}>
        {run.started_by ?? "Unknown"}
      </td>
      <td className={cn(CELL, "font-mono text-muted-foreground")}>
        <span title={run.run_id}>{shortId(run.run_id)}</span>
      </td>
      <td className={CELL}>
        {run.status === "review_required" && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => onReview(run.run_id)}
            aria-label={`Review run ${shortId(run.run_id)}`}
          >
            Review
          </Button>
        )}
      </td>
    </tr>
  );
}

/**
 * The recorded runs, newest first, in a pane of the same height as the console's other tabs.
 * A run that waits for its review has a button that opens it under Review; the other rows do
 * not open.
 */
export function RunsTable({
  status,
  runs,
  onReview,
}: Pick<RunsState, "status" | "runs"> & {
  onReview: (runId: string) => void;
}) {
  return (
    <div className={cn(PANE_HEIGHT, "overflow-auto")}>
      {status === "error" && (
        <p role="alert" className="type-body px-4 pt-4 text-destructive">
          Could not load the runs. Check that the backend is running, then
          refresh.
        </p>
      )}
      {runs.length === 0 ? (
        status !== "error" && (
          <p className="type-body p-4 text-muted-foreground">
            {status === "loading" ? "Loading runs…" : "No runs recorded yet."}
          </p>
        )
      ) : (
        <table className="type-body w-full border-collapse text-left">
          <caption className="sr-only">Recorded runs, newest first</caption>
          <thead className="sticky top-0 bg-muted">
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
            {runs.map((run) => (
              <Row key={run.run_id} run={run} onReview={onReview} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
