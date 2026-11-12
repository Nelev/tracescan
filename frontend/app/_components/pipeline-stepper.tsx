import type { Stage, StageState } from "@/lib/run-overview";
import type { StatusTone } from "@/lib/runs";
import { cn } from "@/lib/utils";
import { Chip, TONE_FILL } from "./chip";

const STATE: Record<StageState, { label: string; tone: StatusTone }> = {
  done: { label: "Done", tone: "success" },
  running: { label: "Running", tone: "info" },
  waiting: { label: "Waiting for you", tone: "warning" },
  failed: { label: "Failed", tone: "destructive" },
  stopped: { label: "Stopped", tone: "stopped" },
  pending: { label: "Pending", tone: "neutral" },
  skipped: { label: "Skipped", tone: "neutral" },
};

function Bar({ stage }: { stage: Stage }) {
  const bar = TONE_FILL[STATE[stage.state].tone];
  if (stage.progress === null) {
    return (
      <span
        className={cn(
          "block h-1.5",
          bar,
          stage.state === "running" && "motion-safe:animate-pulse",
        )}
      />
    );
  }
  return (
    <span className="block h-1.5 overflow-hidden rounded-full bg-track">
      <span
        className={cn("block h-full transition-[width]", bar)}
        style={{ width: `${Math.round(stage.progress * 100)}%` }}
      />
    </span>
  );
}

/**
 * The run's stages in one row: a bar per stage (filled as far as a running fan-out is), what it
 * produced, and where it stands. The current stage's state is also a chip, so it never rests on
 * color alone.
 */
export function PipelineStepper({ stages }: { stages: Stage[] }) {
  return (
    <ol
      aria-label="Pipeline"
      className="grid grid-cols-2 gap-x-3 gap-y-4 sm:grid-cols-4 xl:grid-cols-7"
    >
      {stages.map((stage) => {
        const { label, tone } = STATE[stage.state];
        const current =
          stage.state === "running" ||
          stage.state === "waiting" ||
          stage.state === "failed" ||
          stage.state === "stopped";
        return (
          <li
            key={stage.key}
            aria-current={current ? "step" : undefined}
            aria-label={`${stage.label}: ${label}, ${stage.detail}`}
            className="flex min-w-0 flex-col gap-2"
          >
            <Bar stage={stage} />
            <span className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "type-h3",
                  (stage.state === "pending" || stage.state === "skipped") &&
                    "text-muted-foreground",
                )}
              >
                {stage.label}
              </span>
              {current && (
                <Chip tone={tone} size="sm" live={stage.state === "running"}>
                  {label}
                </Chip>
              )}
            </span>
            <span className="type-body truncate text-muted-foreground tabular-nums">
              {stage.detail}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
