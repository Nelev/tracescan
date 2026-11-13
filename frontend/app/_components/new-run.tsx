"use client";

import { Loader2, Play, Plus } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { MAX_JUDGED_TRACES, type RunRequest } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useRunStatus } from "./run-stream";
import { SEGMENT_ITEM, SEGMENT_LIST } from "./styles";

// The date picker (react-day-picker, date-fns) is only shown for the Custom window, so it is its
// own chunk: about 50 KB gzipped less JavaScript on first load. The chunk starts loading when the
// reader reaches for Custom, so the picker is usually ready by the time it is shown.
const loadDateTimeField = () =>
  import("./date-time-field").then((m) => m.DateTimeField);
const DateTimeField = dynamic(loadDateTimeField);

// The messages of a run draw with json-render, which is its own chunk (agent-console.tsx): it
// starts loading as soon as the reader opens this form, so it is ready when the run page opens.
const preloadConsole = () => {
  void import("./ui-view");
};

type WindowId = "all" | "1h" | "24h" | "7d" | "custom";

const WINDOWS: { id: WindowId; label: string; hours?: number }[] = [
  { id: "all", label: "All" },
  { id: "1h", label: "1h", hours: 1 },
  { id: "24h", label: "24h", hours: 24 },
  { id: "7d", label: "7d", hours: 168 },
  { id: "custom", label: "Custom" },
];

function toIso(local: string): string | undefined {
  return local ? new Date(local).toISOString() : undefined;
}

// Presets are resolved when the run starts, so "1h" is always relative to now.
function windowBounds(
  win: WindowId,
  since: string,
  until: string,
): Pick<RunRequest, "since" | "until"> {
  if (win === "custom") return { since: toIso(since), until: toIso(until) };
  const hours = WINDOWS.find((w) => w.id === win)?.hours;
  if (hours === undefined) return {};
  return { since: new Date(Date.now() - hours * 3_600_000).toISOString() };
}

const APP_REQUIRED = "Enter a target app";

/**
 * The header's New run button and its form: the app and the time window. The form stays open
 * until the server names the run (the window then opens the run's page) or says why it did not
 * start.
 */
export function NewRun() {
  const run = useRunStatus();
  const [open, setOpen] = useState(false);
  const [targetApp, setTargetApp] = useState("medas");
  const [win, setWin] = useState<WindowId>("all");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const running = run.phase === "running";
  const starting = submitted && running && run.runId === null;

  // The run is named: its page opens, so the form is done.
  useEffect(() => {
    if (submitted && run.runId !== null) {
      setOpen(false);
      setSubmitted(false);
    }
  }, [submitted, run.runId]);

  function submit() {
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
    setSubmitted(true);
    void run.start({ target_app: app, ...windowBounds(win, since, until) });
  }

  // Why the last start did not get a run: shown in the form that sent it.
  const startError = submitted && !running ? run.error : null;
  const message = fieldError ?? startError;

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) preloadConsole();
      }}
    >
      <PopoverTrigger
        className={buttonVariants()}
        disabled={running && !starting}
        title={
          running && !starting
            ? "A run is already streaming in this window"
            : undefined
        }
      >
        <Plus aria-hidden="true" />
        New run
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[22rem] gap-4 p-4">
        <PopoverTitle className="type-h2">Start a triage run</PopoverTitle>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="target-app">Target app</Label>
            <Input
              id="target-app"
              className="h-9"
              value={targetApp}
              onChange={(e) => {
                setTargetApp(e.target.value);
                setFieldError(null);
              }}
              disabled={starting}
              aria-invalid={fieldError === APP_REQUIRED}
              aria-describedby={message ? "new-run-error" : undefined}
            />
          </div>

          <fieldset className="flex min-w-0 flex-col gap-2" disabled={starting}>
            <legend className="type-h3 mb-2">Time window</legend>
            <div className={SEGMENT_LIST}>
              {WINDOWS.map((w) => (
                <label
                  key={w.id}
                  onPointerEnter={
                    w.id === "custom" ? loadDateTimeField : undefined
                  }
                  onFocus={w.id === "custom" ? loadDateTimeField : undefined}
                  className={cn(
                    SEGMENT_ITEM,
                    "flex-1 px-2",
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
            <p className="type-body text-muted-foreground">
              A run judges at most the {MAX_JUDGED_TRACES} newest traces in the
              window.
            </p>
          </fieldset>

          {win === "custom" && (
            <div className="flex flex-col gap-3">
              <DateTimeField
                id="since"
                label="Since"
                value={since}
                onChange={(v) => {
                  setSince(v);
                  setFieldError(null);
                }}
              />
              <DateTimeField
                id="until"
                label="Until"
                value={until}
                onChange={(v) => {
                  setUntil(v);
                  setFieldError(null);
                }}
              />
            </div>
          )}

          {message && (
            <p
              id="new-run-error"
              role="alert"
              className="type-body text-destructive"
            >
              {message}
            </p>
          )}

          <div className="flex justify-end gap-2">
            {starting && (
              <Button type="button" variant="outline" onClick={run.cancel}>
                Cancel
              </Button>
            )}
            <Button type="submit" disabled={starting} aria-busy={starting}>
              {starting ? (
                <Loader2
                  className="motion-safe:animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Play aria-hidden="true" />
              )}
              {starting ? "Starting…" : "Run triage"}
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
