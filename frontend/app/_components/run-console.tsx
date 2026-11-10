"use client";

import { Check, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { RunView } from "@/lib/run-view";
import { RUN_EVENTS } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RunProgress } from "./run-progress";
import type { Phase } from "./use-run-stream";

// The messages draw with json-render, zod and the package's components, which the progress tab
// does not need: their own chunk. It starts loading when the reader reaches for the Console tab or
// a run starts (its messages arrive right after), so it is usually ready by the time it is shown.
const loadUiMessages = () => import("./ui-view").then((m) => m.UiMessages);
const preloadUiMessages = () => {
  void loadUiMessages();
};
const UiMessages = dynamic(loadUiMessages, {
  loading: () => (
    <p className="type-body p-4 text-muted-foreground">Loading…</p>
  ),
});

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

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  return `${mm}:${String(total % 60).padStart(2, "0")}`;
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

type Tab = "progress" | "console";

export function RunConsole({
  view,
  phase,
  error,
  events,
  startedAt,
  endedAt,
  onClear,
}: {
  view: RunView;
  phase: Phase;
  /** Why the run did not start or was cut short; shown above the messages. */
  error: string | null;
  events: number;
  startedAt: number | null;
  endedAt: number | null;
  onClear: () => void;
}) {
  const running = phase === "running";
  const scrollRef = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<Tab>("progress");

  useEffect(() => {
    if (running) preloadUiMessages();
  }, [running]);

  // Follow the newest message, unless the reader scrolled up to look at an earlier one. The console
  // mounts only while its tab is open, so opening the tab scrolls it to the newest message too.
  const messages = view.messages;
  // biome-ignore lint/correctness/useExhaustiveDependencies: the count and the tab are the triggers
  useEffect(() => {
    const el = scrollRef.current;
    if (el && following.current) el.scrollTop = el.scrollHeight;
  }, [messages.length, tab]);

  function onScroll() {
    const el = scrollRef.current;
    if (el) {
      following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    }
  }

  async function copy() {
    try {
      const specs = messages.map(({ event, spec }) => ({ event, spec }));
      await navigator.clipboard.writeText(JSON.stringify(specs, null, 2));
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
            <TabsTrigger value="progress">Progress</TabsTrigger>
            <TabsTrigger
              value="console"
              onMouseEnter={preloadUiMessages}
              onFocus={preloadUiMessages}
            >
              Console
            </TabsTrigger>
          </TabsList>
          <StatusChip phase={phase} />
        </div>
        <div className="flex gap-2">
          {tab === "console" && (
            <Button
              variant="outline"
              onClick={copy}
              disabled={messages.length === 0}
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          )}
          <Button
            variant="outline"
            onClick={() => {
              following.current = true;
              onClear();
            }}
            disabled={running || phase === "idle"}
          >
            Clear
          </Button>
        </div>
      </div>

      {/* Both panels have the same fixed height, so switching tabs does not move the page. */}
      <div className="mx-6 rounded-xl border bg-muted shadow-[inset_0_2px_8px_0_oklch(0.05_0.05_265/0.6)]">
        <TabsContent value="progress" className="h-[36rem] sm:h-[28.75rem]">
          <RunProgress view={view} phase={phase} />
        </TabsContent>
        <TabsContent value="console">
          <div
            ref={scrollRef}
            onScroll={onScroll}
            className="h-[36rem] overflow-y-auto sm:h-[28.75rem]"
          >
            {error && (
              <p role="alert" className="type-body px-4 pt-4 text-destructive">
                {error}
              </p>
            )}
            <UiMessages messages={messages} phase={phase} />
          </div>
        </TabsContent>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-6 pt-3 pb-6">
        <span className="type-h4">{PHASE[phase].footer(events)}</span>
        <Elapsed startedAt={startedAt} endedAt={endedAt} />
      </div>
    </Tabs>
  );
}
