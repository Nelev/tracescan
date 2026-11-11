"use client";

import { Loader2, Play, RotateCcw } from "lucide-react";
import dynamic from "next/dynamic";
import { type ChangeEvent, type ComponentProps, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SEGMENT_ITEM, SEGMENT_LIST } from "@/components/ui/tabs";
import type { RunRequest } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RunConsole } from "./run-console";
import { useRunStream } from "./use-run-stream";

// The date picker (react-day-picker, date-fns) is only shown for the Custom window, so it is its
// own chunk: about 50 KB gzipped less JavaScript on first load. The chunk starts loading when the
// reader reaches for Custom, so the picker is usually ready by the time it is shown.
const loadDateTimeField = () =>
  import("./date-time-field").then((m) => m.DateTimeField);
const DateTimeField = dynamic(loadDateTimeField);

type WindowId = "all" | "1h" | "24h" | "7d" | "custom";

const WINDOWS: { id: WindowId; label: string; hours?: number }[] = [
  { id: "all", label: "All" },
  { id: "1h", label: "1h", hours: 1 },
  { id: "24h", label: "24h", hours: 24 },
  { id: "7d", label: "7d", hours: 168 },
  { id: "custom", label: "Custom" },
];

const WINDOW_BY_ID = Object.fromEntries(
  WINDOWS.map((w) => [w.id, w]),
) as Record<WindowId, (typeof WINDOWS)[number]>;

const SUBMIT = {
  idle: { Icon: Play, label: "Run triage" },
  retry: { Icon: RotateCcw, label: "Run again" },
  running: { Icon: Loader2, label: "Running…" },
};

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

const APP_REQUIRED = "Enter a target app";

function Field({
  id,
  label,
  className,
  ...inputProps
}: { id: string; label: string } & ComponentProps<typeof Input>) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} className={cn("h-9", className)} {...inputProps} />
    </div>
  );
}

export function RunPanel() {
  const [targetApp, setTargetApp] = useState("medas");
  // All, not a recent window: the trace store is still the fixture, dated 2026-11-05.
  const [win, setWin] = useState<WindowId>("all");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const run = useRunStream();

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
    run.start({ target_app: app, ...windowBounds(win, since, until) });
  }

  const running = run.phase === "running";
  const retry = run.phase === "failed" || run.phase === "lost";
  const { Icon, label } =
    SUBMIT[running ? "running" : retry ? "retry" : "idle"];

  // Field handlers: store the value and clear any stale validation message.
  const pick = (set: (value: string) => void) => (value: string) => {
    set(value);
    setFieldError(null);
  };
  const edit =
    (set: (value: string) => void) => (e: ChangeEvent<HTMLInputElement>) =>
      pick(set)(e.target.value);

  return (
    <Card className="flex-1 gap-0 py-0">
      <form
        className="flex flex-wrap items-end gap-x-6 gap-y-4 border-b p-6"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Field
          id="target-app"
          label="Target app"
          className="w-52"
          value={targetApp}
          onChange={edit(setTargetApp)}
          disabled={running}
          aria-invalid={fieldError === APP_REQUIRED}
          aria-describedby={fieldError ? "form-error" : undefined}
        />

        <fieldset className="flex min-w-0 flex-col gap-2" disabled={running}>
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
                  "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
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
        </fieldset>

        <div className="ml-auto flex gap-2">
          {running && (
            <Button
              type="button"
              variant="outline"
              size="lg"
              onClick={run.cancel}
            >
              Cancel
            </Button>
          )}
          <Button
            type="submit"
            size="lg"
            disabled={running}
            aria-busy={running}
          >
            <Icon
              className={cn(running && "motion-safe:animate-spin")}
              aria-hidden="true"
            />
            {label}
          </Button>
        </div>

        {win === "custom" && (
          <div className="flex basis-full flex-wrap gap-4">
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

        {fieldError && (
          <p
            id="form-error"
            role="alert"
            className="type-body basis-full text-destructive"
          >
            {fieldError}
          </p>
        )}
      </form>

      <RunConsole
        lines={run.lines}
        messages={run.messages}
        phase={run.phase}
        runId={run.runId}
        onReviewed={run.markReviewed}
        error={run.error}
        events={run.events}
        startedAt={run.startedAt}
        endedAt={run.endedAt}
        onClear={run.clear}
      />
    </Card>
  );
}
