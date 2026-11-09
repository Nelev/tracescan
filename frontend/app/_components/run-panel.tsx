"use client";

import { AlertCircle, ChevronRight, Loader2, Play } from "lucide-react";
import {
  type ChangeEvent,
  type ComponentProps,
  useEffect,
  useRef,
  useState,
} from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { RunError, runTriage } from "@/lib/api";
import type { RunRequest, RunResponse } from "@/lib/types";
import { cn } from "@/lib/utils";
import { DateTimeField, formatLocal } from "./date-time-field";

type RunState =
  | { status: "idle" }
  | { status: "running" }
  | { status: "success"; result: RunResponse }
  | { status: "error"; error: RunError };

type WindowId = "all" | "1h" | "24h" | "7d" | "custom";

const WINDOWS: {
  id: WindowId;
  label: string;
  summary: string;
  hours?: number;
}[] = [
  { id: "all", label: "All", summary: "All traces, no time limit" },
  { id: "1h", label: "1h", summary: "Last hour", hours: 1 },
  { id: "24h", label: "24h", summary: "Last 24 hours", hours: 24 },
  { id: "7d", label: "7d", summary: "Last 7 days", hours: 168 },
  { id: "custom", label: "Custom", summary: "" },
];

const WINDOW_BY_ID = Object.fromEntries(
  WINDOWS.map((w) => [w.id, w]),
) as Record<WindowId, (typeof WINDOWS)[number]>;

// Lines look like "[dry-run] create_issue c0": the leading tag is split off so it can stand out.
const LOG_TAG = /^\[([^\]]+)\]\s*(.*)$/;

function toIso(local: string): string | undefined {
  return local ? new Date(local).toISOString() : undefined;
}

// Presets are resolved when the run starts, so "Last hour" is always relative to now.
function windowBounds(
  win: WindowId,
  since: string,
  until: string,
): Pick<RunRequest, "since" | "until"> {
  if (win === "custom") return { since: toIso(since), until: toIso(until) };
  const hours = WINDOW_BY_ID[win].hours;
  if (hours === undefined) return {};
  return { since: new Date(Date.now() - hours * 3_600_000).toISOString() };
}

const STATUS_LABEL: Record<RunState["status"], string> = {
  idle: "Idle",
  running: "Running…",
  success: "Done",
  error: "Failed",
};

function Stat({
  label,
  value,
  last = false,
}: {
  label: string;
  value: number;
  last?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative rounded-lg border bg-muted px-3 py-2.5 shadow-[inset_0_1px_0_0_oklch(1_0_0/0.04)]",
        last &&
          "border-primary/50 bg-primary/10 shadow-[0_0_24px_-8px] shadow-primary",
      )}
    >
      <dt className="type-h4">{label}</dt>
      <dd
        className={cn("type-h1 font-mono tabular-nums", last && "text-primary")}
      >
        {value}
      </dd>
      {!last && (
        <ChevronRight
          className="absolute top-1/2 -right-3.5 hidden size-4 -translate-y-1/2 text-muted-foreground sm:block"
          aria-hidden="true"
        />
      )}
    </div>
  );
}

function LogLine({ line }: { line: string }) {
  const match = LOG_TAG.exec(line);
  if (!match)
    return <span className="whitespace-pre-wrap break-words">{line}</span>;
  return (
    <span className="whitespace-pre-wrap break-words">
      <span className="mr-2 rounded bg-primary/10 px-1.5 py-0.5 text-primary">
        {match[1]}
      </span>
      {match[2]}
    </span>
  );
}

function errorMessage(error: RunError): string {
  if (error.status === null) {
    return "Couldn't reach the backend. Check that it's running, then retry.";
  }
  // The dev proxy answers 500 when the backend is down, so both causes are listed.
  return `The run failed (HTTP ${error.status}). Check that the backend is running and look at its logs, then retry.`;
}

const APP_REQUIRED = "Enter a target app";

function Field({
  id,
  label,
  ...inputProps
}: { id: string; label: string } & ComponentProps<typeof Input>) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} className="h-9" {...inputProps} />
    </div>
  );
}

export function RunPanel() {
  const [targetApp, setTargetApp] = useState("medas");
  const [win, setWin] = useState<WindowId>("all");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [state, setState] = useState<RunState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (state.status === "success" || state.status === "error") {
      headingRef.current?.focus();
    }
  }, [state.status]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function start() {
    const app = targetApp.trim();
    if (!app) {
      setFieldError(APP_REQUIRED);
      return;
    }
    if (
      win === "custom" &&
      since &&
      until &&
      new Date(since) >= new Date(until)
    ) {
      setFieldError("Since must be before until");
      return;
    }
    setFieldError(null);

    const body: RunRequest = {
      target_app: app,
      ...windowBounds(win, since, until),
    };
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: "running" });

    try {
      const result = await runTriage(body, controller.signal);
      setState({ status: "success", result });
    } catch (err) {
      if (controller.signal.aborted) return;
      setState({
        status: "error",
        error: err instanceof RunError ? err : new RunError(null),
      });
    }
  }

  function cancel() {
    abortRef.current?.abort();
    setState({ status: "idle" });
  }

  const running = state.status === "running";

  // Field handlers: store the value and clear any stale validation message.
  const pick = (set: (value: string) => void) => (value: string) => {
    set(value);
    setFieldError(null);
  };
  const edit =
    (set: (value: string) => void) => (e: ChangeEvent<HTMLInputElement>) =>
      pick(set)(e.target.value);

  return (
    <div className="grid items-start gap-4 lg:grid-cols-12">
      <Card className="lg:sticky lg:top-20 lg:col-span-4 xl:col-span-3">
        <CardHeader>
          <CardTitle>Run triage</CardTitle>
          <CardDescription>
            Reads failed traces, clusters them, and drafts proposals.
          </CardDescription>
        </CardHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            start();
          }}
        >
          <CardContent className="flex flex-col gap-5">
            <Field
              id="target-app"
              label="Target app"
              value={targetApp}
              onChange={edit(setTargetApp)}
              aria-invalid={fieldError === APP_REQUIRED}
              aria-describedby={fieldError ? "form-error" : undefined}
            />

            <fieldset className="flex min-w-0 flex-col gap-3">
              <legend className="type-h3 mb-2">Time window</legend>
              <div className="grid grid-cols-[repeat(4,1fr)_1.7fr] gap-1 rounded-lg border bg-muted p-1">
                {WINDOWS.map((w) => (
                  <label
                    key={w.id}
                    className={cn(
                      "type-body cursor-pointer rounded-md py-1.5 text-center text-muted-foreground transition-colors select-none hover:text-foreground has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                      win === w.id &&
                        "bg-primary text-primary-foreground hover:text-primary-foreground",
                    )}
                  >
                    <input
                      type="radio"
                      name="time-window"
                      value={w.id}
                      checked={win === w.id}
                      onChange={() => {
                        setWin(w.id);
                        setFieldError(null);
                      }}
                      className="sr-only"
                    />
                    {w.label}
                  </label>
                ))}
              </div>

              {win === "custom" && (
                <div className="flex flex-col gap-3 rounded-lg border bg-muted/50 p-3">
                  <DateTimeField
                    id="since"
                    label="Since"
                    value={since}
                    onChange={pick(setSince)}
                  />
                  <DateTimeField
                    id="until"
                    label="Until"
                    value={until}
                    onChange={pick(setUntil)}
                  />
                </div>
              )}

              <p className="type-body text-muted-foreground">
                {win === "custom"
                  ? `${formatLocal(since, "The beginning")} → ${formatLocal(until, "now")}`
                  : WINDOW_BY_ID[win].summary}
              </p>
            </fieldset>

            {fieldError && (
              <p
                id="form-error"
                role="alert"
                className="type-body text-destructive"
              >
                {fieldError}
              </p>
            )}

            <div className="flex gap-2">
              {running && (
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  onClick={cancel}
                >
                  Cancel
                </Button>
              )}
              <Button
                type="submit"
                size="lg"
                className="flex-1"
                disabled={running}
                aria-busy={running}
              >
                {running ? (
                  <Loader2 className="animate-spin" aria-hidden="true" />
                ) : (
                  <Play aria-hidden="true" />
                )}
                {running ? "Running…" : "Run triage"}
              </Button>
            </div>
          </CardContent>
        </form>
      </Card>

      <Card aria-live="polite" className="min-h-80 lg:col-span-8 xl:col-span-9">
        <CardHeader>
          <CardTitle ref={headingRef} tabIndex={-1} className="outline-none">
            Output
          </CardTitle>
          <CardAction>
            <span className="type-h4">{STATUS_LABEL[state.status]}</span>
          </CardAction>
        </CardHeader>
        <CardContent>
          {state.status === "idle" && (
            <p className="type-body text-muted-foreground">
              Run a triage to see results.
            </p>
          )}
          {state.status === "running" && (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-16" />
              <Skeleton className="h-28" />
            </div>
          )}
          {state.status === "error" && (
            <Alert variant="destructive">
              <AlertCircle aria-hidden="true" />
              <AlertTitle>Triage run failed</AlertTitle>
              <AlertDescription>{errorMessage(state.error)}</AlertDescription>
            </Alert>
          )}
          {state.status === "success" && <Result result={state.result} />}
        </CardContent>
        {state.status === "error" && (
          <CardFooter className="justify-end">
            <Button variant="outline" onClick={start}>
              Retry
            </Button>
          </CardFooter>
        )}
      </Card>
    </div>
  );
}

function Result({ result }: { result: RunResponse }) {
  const empty = result.failed_traces === 0;
  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
        <Stat label="Failed traces" value={result.failed_traces} />
        <Stat label="Clusters" value={result.clusters} />
        <Stat label="Diagnoses" value={result.diagnoses} />
        <Stat label="Proposals" value={result.proposals} last />
      </dl>
      {result.unclustered > 0 && (
        <p className="type-body text-muted-foreground">
          {result.unclustered} failed trace(s) fit no cluster and were not
          diagnosed.
        </p>
      )}
      {empty && (
        <div>
          <h3>No failures in this window</h3>
          <p className="type-body text-muted-foreground">
            Widen the time window or pick another app.
          </p>
        </div>
      )}
      {result.actions_log.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <h4>Actions log</h4>
          <ol className="type-body max-h-56 overflow-auto rounded-lg border bg-background/70 p-3 font-mono text-foreground shadow-[inset_0_2px_8px_0_oklch(0.05_0.05_265/0.6)]">
            {result.actions_log.map((line, i) => (
              // The log is append-only text and can repeat, so the index is the only stable key.
              // biome-ignore lint/suspicious/noArrayIndexKey: see above
              <li key={i} className="flex gap-3">
                <span className="select-none text-muted-foreground">
                  {i + 1}
                </span>
                <LogLine line={line} />
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
