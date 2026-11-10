"use client";

import { Check, X } from "lucide-react";
import dynamic from "next/dynamic";
import { memo, type ReactNode, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { UiMessage } from "@/lib/events";
import { RUN_EVENTS } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { ConsoleLine, Phase, Tone } from "./use-run-stream";

// The messages draw with json-render, zod and the package's components, which the page does not
// need until a run sends its first message: their own chunk. It starts loading when a run starts
// (its messages arrive right after), so it is usually ready by the time it is shown.
const loadUiMessages = () => import("./ui-view").then((m) => m.UiMessages);
const preloadUiMessages = () => {
  void loadUiMessages();
};
const UiMessages = dynamic(loadUiMessages, {
  loading: () => (
    <p className="type-body p-4 text-muted-foreground">Loading…</p>
  ),
});

const TONE: Record<Tone, string> = {
  muted: "text-muted-foreground",
  run: "text-ring",
  ok: "text-success",
  bad: "text-destructive",
};

const SUCCESS = "border-success/30 bg-success/10 text-success";
const DESTRUCTIVE = "border-destructive/40 bg-destructive/10 text-destructive";

const channel = (state: string) => (events: number) =>
  `${state} · text/event-stream · ${events} ${events === 1 ? "event" : "events"}`;

/** What each phase shows: the status chip and the footer line. */
const PHASE: Record<
  Phase,
  { label: string; className: string; footer: (events: number) => string }
> = {
  idle: {
    label: "Idle",
    className: "text-muted-foreground",
    footer: () => "Not connected",
  },
  running: {
    label: "Streaming",
    className: "border-ring bg-accent text-foreground",
    footer: channel("Connected"),
  },
  done: { label: "Done", className: SUCCESS, footer: channel("Closed") },
  failed: {
    label: "Failed",
    className: DESTRUCTIVE,
    // run_started always comes first, so no events means the run never started.
    footer: (events) =>
      events === 0
        ? "Not connected"
        : channel(`Closed by ${RUN_EVENTS.failed}`)(events),
  },
  lost: {
    label: "Connection lost",
    className: DESTRUCTIVE,
    footer: channel("Closed early"),
  },
  cancelled: {
    label: "Cancelled",
    className: "text-muted-foreground",
    footer: channel("Cancelled by you"),
  },
};

function formatAt(ms: number): string {
  const s = ms / 1000;
  return `+${s < 10 ? s.toFixed(2) : s.toFixed(1)}s`;
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  return `${mm}:${String(total % 60).padStart(2, "0")}`;
}

function toText(lines: ConsoleLine[]): string {
  return lines
    .map((l) =>
      [l.at === undefined ? "" : formatAt(l.at), l.label ?? "", l.text]
        .filter(Boolean)
        .join("  "),
    )
    .join("\n");
}

/** The clock ticks here, in a leaf, so the log is not re-rendered every second. */
function Elapsed({
  startedAt,
  endedAt,
}: {
  startedAt: number | null;
  endedAt: number | null;
}) {
  const running = startedAt !== null && endedAt === null;
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(performance.now()), 1000);
    return () => clearInterval(id);
  }, [running]);
  const ms = startedAt === null ? 0 : (endedAt ?? now) - startedAt;
  return <span className="type-h4">Elapsed {formatElapsed(ms)}</span>;
}

/** An <output> is a live region, so a screen reader announces each phase change. */
function StatusChip({ phase }: { phase: Phase }) {
  const { label, className } = PHASE[phase];
  return (
    <output
      className={cn(
        "inline-flex h-7 items-center gap-2 rounded-full border px-3",
        className,
      )}
    >
      {phase === "running" && (
        <span
          className="size-2 rounded-full bg-ring motion-safe:animate-pulse"
          aria-hidden="true"
        />
      )}
      {phase === "done" && <Check className="size-4" aria-hidden="true" />}
      {(phase === "failed" || phase === "lost") && (
        <X className="size-4" aria-hidden="true" />
      )}
      <span className="type-h4 text-current">{label}</span>
    </output>
  );
}

// A line never changes once printed, so a new batch re-renders only the lines it adds.
const Line = memo(function Line({ line }: { line: ConsoleLine }) {
  const head = line.at !== undefined || line.label !== undefined;
  return (
    <li className="flex flex-col gap-0.5 sm:grid sm:grid-cols-[4rem_9rem_minmax(0,1fr)] sm:items-baseline sm:gap-x-4">
      {head && (
        <span className="flex gap-3 sm:contents">
          <span className="text-muted-foreground">
            {line.at === undefined ? "" : formatAt(line.at)}
          </span>
          <span className={TONE[line.tone ?? "muted"]}>{line.label}</span>
        </span>
      )}
      <span
        className={cn(
          "whitespace-pre-wrap [overflow-wrap:anywhere]",
          !head && "text-muted-foreground sm:col-start-3",
        )}
      >
        {line.text}
      </span>
    </li>
  );
});

function emptyText(phase: Phase): string {
  if (phase === "idle") return "Run a triage to see its messages here.";
  if (phase === "running") return "Waiting for the first message…";
  return "The run sent no message that could be shown.";
}

/**
 * A fixed-height pane that follows its newest entry, unless the reader scrolled up to look at an
 * earlier one. `watch` changes whenever an entry is added and is 0 when the run is cleared, which
 * follows again. Only the open tab's pane is mounted, so opening a tab scrolls it to its newest
 * entry too.
 */
function ScrollPane({
  watch,
  children,
}: {
  watch: number;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const following = useRef(true);

  useEffect(() => {
    if (watch === 0) following.current = true;
    const el = ref.current;
    if (el && following.current) el.scrollTop = el.scrollHeight;
  }, [watch]);

  function onScroll() {
    const el = ref.current;
    if (el) {
      following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    }
  }

  return (
    <div
      ref={ref}
      onScroll={onScroll}
      className="h-[36rem] overflow-y-auto sm:h-[28.75rem]"
    >
      {children}
    </div>
  );
}

type Tab = "console" | "raw";

/**
 * The page's whole output: the messages the server streams, drawn from the UI specs its model
 * wrote (Console), and the same stream as received (Raw events).
 */
export function RunConsole({
  lines,
  messages,
  phase,
  error,
  events,
  startedAt,
  endedAt,
  onClear,
}: {
  lines: ConsoleLine[];
  messages: UiMessage[];
  phase: Phase;
  /** Why the run did not start or was cut short; shown above the messages. */
  error: string | null;
  events: number;
  startedAt: number | null;
  endedAt: number | null;
  onClear: () => void;
}) {
  const running = phase === "running";
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<Tab>("console");

  useEffect(() => {
    if (running) preloadUiMessages();
  }, [running]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(
        tab === "console"
          ? JSON.stringify(
              messages.map(({ event, spec }) => ({ event, spec })),
              null,
              2,
            )
          : toText(lines),
      );
    } catch {
      return; // no clipboard in this context
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="sr-only">Run output</h2>
          <TabsList aria-label="Run output">
            <TabsTrigger value="console">Console</TabsTrigger>
            <TabsTrigger value="raw">Raw events</TabsTrigger>
          </TabsList>
          <StatusChip phase={phase} />
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={copy}
            disabled={(tab === "console" ? messages : lines).length === 0}
          >
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button
            variant="outline"
            onClick={onClear}
            disabled={running || phase === "idle"}
          >
            Clear
          </Button>
        </div>
      </div>

      {/* Both panels have the same fixed height, so switching tabs does not move the page. */}
      <div className="mx-6 rounded-xl border bg-muted shadow-[inset_0_2px_8px_0_oklch(0.05_0.05_265/0.6)]">
        <TabsContent value="console">
          <ScrollPane watch={messages.length}>
            {error && (
              <p role="alert" className="type-body px-4 pt-4 text-destructive">
                {error}
              </p>
            )}
            {messages.length === 0 ? (
              <p className="type-body p-4 text-muted-foreground">
                {emptyText(phase)}
              </p>
            ) : (
              <UiMessages messages={messages} />
            )}
          </ScrollPane>
        </TabsContent>
        <TabsContent value="raw">
          <ScrollPane watch={lines.at(-1)?.id ?? 0}>
            <ol
              role="log"
              aria-label="Events as they arrive"
              className="type-body flex min-h-full flex-col justify-end gap-2 p-4 font-mono"
            >
              {lines.length === 0 ? (
                <li className="text-muted-foreground">
                  Run a triage to see its events here.
                </li>
              ) : (
                lines.map((line) => <Line key={line.id} line={line} />)
              )}
              {running && (
                <li aria-hidden="true">
                  <span className="inline-block h-4 w-2 bg-primary align-[-3px] motion-safe:animate-pulse" />
                </li>
              )}
            </ol>
          </ScrollPane>
        </TabsContent>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-6 pt-3 pb-6">
        <span className="type-h4">{PHASE[phase].footer(events)}</span>
        <Elapsed startedAt={startedAt} endedAt={endedAt} />
      </div>
    </Tabs>
  );
}
