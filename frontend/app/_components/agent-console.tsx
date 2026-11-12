"use client";

import dynamic from "next/dynamic";
import { memo, type ReactNode, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { useRun } from "./run-stream";
import { TypingDots } from "./typing-dots";
import type { ConsoleLine, Tone } from "./use-run-stream";

// The messages draw with json-render, zod and the package's components: their own chunk, which
// starts loading when the New run form opens (new-run.tsx).
const UiMessages = dynamic(
  () => import("./ui-view").then((m) => m.UiMessages),
  {
    loading: () => (
      <p className="type-body p-4 text-muted-foreground">Loading…</p>
    ),
  },
);

const TONE: Record<Tone, string> = {
  muted: "text-muted-foreground",
  run: "text-ring",
  ok: "text-success",
  bad: "text-destructive",
};

function formatAt(ms: number): string {
  const s = ms / 1000;
  return `+${s < 10 ? s.toFixed(2) : s.toFixed(1)}s`;
}

// A line never changes once printed, so a new batch re-renders only the lines it adds.
const Line = memo(function Line({ line }: { line: ConsoleLine }) {
  return (
    <li className="flex flex-col gap-0.5">
      {(line.at !== undefined || line.label !== undefined) && (
        <span className="flex gap-3">
          <span className="text-muted-foreground">
            {line.at === undefined ? "" : formatAt(line.at)}
          </span>
          <span className={TONE[line.tone ?? "muted"]}>{line.label}</span>
        </span>
      )}
      <span
        className={cn(
          "whitespace-pre-wrap [overflow-wrap:anywhere]",
          line.label === undefined && "text-muted-foreground",
        )}
      >
        {line.text}
      </span>
    </li>
  );
});

/**
 * A pane that follows its newest entry, unless the reader scrolled up to look at an earlier one.
 * `watch` changes whenever an entry is added.
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
    const el = ref.current;
    if (el && following.current && watch >= 0) el.scrollTop = el.scrollHeight;
  }, [watch]);

  return (
    <div
      ref={ref}
      onScroll={() => {
        const el = ref.current;
        if (el) {
          following.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }
      }}
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
    >
      {children}
    </div>
  );
}

/**
 * The agent's own account of this window's run, for the console dock: each message the server
 * streams, drawn from the UI spec its small model wrote for it (json-render), or with `raw` on,
 * every event as received. Both follow their newest entry unless the reader scrolled up.
 */
export function ConsoleFeed({ raw }: { raw: boolean }) {
  const run = useRun();
  const running = run.phase === "running";

  return raw ? (
    <ScrollPane watch={run.lines.at(-1)?.id ?? 0}>
      <ol
        role="log"
        aria-label="Events as they arrive"
        className="type-body flex flex-col gap-2 p-4 font-mono"
      >
        {run.lines.map((line) => (
          <Line key={line.id} line={line} />
        ))}
      </ol>
    </ScrollPane>
  ) : (
    <ScrollPane watch={run.messages.length}>
      {run.error && (
        <p role="alert" className="type-body px-4 pt-4 text-destructive">
          {run.error}
        </p>
      )}
      {run.messages.length === 0 ? (
        <p className="type-body p-4 text-muted-foreground">
          {running ? (
            <span className="inline-flex items-center gap-2">
              Waiting for the first message
              <TypingDots label="" />
            </span>
          ) : (
            "The run sent no message that could be shown."
          )}
        </p>
      ) : (
        <UiMessages messages={run.messages} />
      )}
    </ScrollPane>
  );
}
