"use client";

import { ChevronDown, MessagesSquare, Minus } from "lucide-react";
import Link from "next/link";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  badgeText,
  DOCK_STATUS,
  dockPhase,
  unreadCount,
  unreadText,
} from "@/lib/dock";
import { runPath, shortId } from "@/lib/runs";
import { cn } from "@/lib/utils";
import { ConsoleFeed } from "./agent-console";
import { Chip } from "./chip";
import { useRun } from "./run-stream";
import { LINK } from "./styles";
import { TypingDots } from "./typing-dots";

const PANEL_ID = "console-dock-panel";

/** A small control's hit area, widened to 40px by a pseudo-element (see CLAUDE.md). */
const HIT = "relative after:absolute after:-inset-1.5 after:content-['']";

/**
 * The agent console as a chat box in the bottom right corner, on every page while this window has
 * a run: a round launcher that opens into a panel and minimizes back. Closed, the launcher shows
 * typing dots while the run streams and a badge of the messages that arrived since it was last
 * open (read out once, as a phrase). Open, the panel holds the run's messages (or its raw events),
 * a link to the run, and where the run stands, with Cancel while it streams. It is not a modal:
 * the page stays usable, Escape minimizes it and gives focus back to the launcher. A run started
 * in this window opens it once; minimized during that run, it stays minimized. The shell owns
 * whether it is open, so the page can leave room for it.
 */
export function ConsoleDock({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const run = useRun();
  const [raw, setRaw] = useState(false);
  // How many messages had arrived when the panel was last open.
  const [seen, setSeen] = useState(0);
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const lastRun = useRef<string | null>(null);
  // Set when the reader opens the panel, so focus moves into it; an automatic open never takes
  // focus away from what the reader was doing.
  const focusOnOpen = useRef(false);
  const total = run.messages.length;

  useEffect(() => {
    if (run.runId === null || run.runId === lastRun.current) return;
    lastRun.current = run.runId;
    setSeen(0);
    if (run.phase === "running") onOpenChange(true);
  }, [run.runId, run.phase, onOpenChange]);

  useEffect(() => {
    if (open) setSeen(total);
  }, [open, total]);

  useEffect(() => {
    if (open && focusOnOpen.current) {
      focusOnOpen.current = false;
      panel.current?.focus();
    }
  }, [open]);

  if (run.runId === null) return null;

  const runId = run.runId;
  const phase = dockPhase(run.phase, run.live.nodes.human_review === "paused");
  const running = phase === "running";
  const status = DOCK_STATUS[phase];
  const unread = unreadCount(total, seen, open);
  const badge = badgeText(unread);

  function toggle() {
    if (!open) focusOnOpen.current = true;
    onOpenChange(!open);
  }

  function minimize() {
    onOpenChange(false);
    launcher.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      minimize();
    }
  }

  return (
    <div className="pointer-events-none fixed right-(--dock-inset) bottom-(--dock-inset) z-console flex flex-col items-end gap-3">
      {open && (
        <section
          ref={panel}
          id={PANEL_ID}
          aria-labelledby="console-dock-title"
          tabIndex={-1}
          onKeyDown={onKeyDown}
          className="surface-raised pointer-events-auto flex h-(--dock-height) w-(--dock-width) max-w-[calc(100vw-2*var(--dock-inset))] origin-bottom-right flex-col overflow-hidden rounded-2xl border outline-none motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95 motion-safe:duration-200"
        >
          <header className="flex items-center gap-2 border-b px-4 py-2">
            <MessagesSquare
              className="size-4 shrink-0 text-primary"
              aria-hidden="true"
            />
            <h2 id="console-dock-title" className="type-h3 whitespace-nowrap">
              Agent console
            </h2>
            <Link
              href={runPath(runId)}
              className={cn(LINK, "type-body min-w-0 truncate")}
              title={`Open run ${runId}`}
            >
              {shortId(runId)}
            </Link>
            <span className="ml-auto flex items-center gap-1">
              <Button
                variant={raw ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={raw}
                onClick={() => setRaw((on) => !on)}
                className={HIT}
              >
                Raw events
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Minimize the agent console"
                onClick={minimize}
                className={HIT}
              >
                <Minus aria-hidden="true" />
              </Button>
            </span>
          </header>
          <ConsoleFeed raw={raw} />
          <footer className="type-body flex items-center gap-3 border-t px-4 py-2 text-muted-foreground">
            <Chip tone={status.tone} size="sm" live={running}>
              {status.label}
            </Chip>
            <span className="min-w-0 flex-1 truncate" title={status.line}>
              {status.line}
            </span>
            {running && (
              <Button variant="outline" size="sm" onClick={run.cancel}>
                Cancel run
              </Button>
            )}
          </footer>
        </section>
      )}

      <button
        ref={launcher}
        type="button"
        aria-expanded={open}
        aria-controls={open ? PANEL_ID : undefined}
        aria-label={`${open ? "Minimize" : "Open"} the agent console${running ? " (the run is streaming)" : ""}`}
        onClick={toggle}
        className="pointer-events-auto relative flex size-(--dock-launcher) items-center justify-center rounded-full bg-primary text-primary-foreground shadow-glow transition-[background-color,box-shadow,scale] hover:bg-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-safe:active:scale-95"
      >
        {open ? (
          <ChevronDown className="size-6" aria-hidden="true" />
        ) : (
          <MessagesSquare className="size-6" aria-hidden="true" />
        )}
        {!open && running && (
          <span className="absolute -bottom-1.5 left-1/2 flex -translate-x-1/2 rounded-full border bg-card px-1.5 py-1">
            <TypingDots label="" />
          </span>
        )}
        {!open && badge && (
          <span
            className="type-body absolute -top-1 -right-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-foreground px-1 font-medium leading-none text-background tabular-nums ring-2 ring-background"
            aria-hidden="true"
          >
            {badge}
          </span>
        )}
      </button>
      {/* The new-message count, read out once as a whole phrase, without moving focus. */}
      <p className="sr-only" aria-live="polite">
        {unreadText(unread)}
      </p>
    </div>
  );
}
