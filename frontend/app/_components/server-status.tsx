"use client";

import { useEffect, useState } from "react";
import { checkHealth } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CHIP_TONE } from "./chip";

type Status = "checking" | "online" | "offline";

const POLL_MS = 15_000;

const STATUS: Record<Status, { label: string; box: string; dot: string }> = {
  checking: {
    label: "Checking backend…",
    box: CHIP_TONE.neutral,
    dot: "motion-safe:animate-pulse bg-muted-foreground",
  },
  online: {
    label: "Backend online",
    box: CHIP_TONE.success,
    dot: "bg-success",
  },
  offline: {
    label: "Backend offline",
    box: CHIP_TONE.destructive,
    dot: "bg-destructive",
  },
};

export function ServerStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();

    async function poll() {
      const ok = await checkHealth(controller.signal);
      if (!controller.signal.aborted) setStatus(ok ? "online" : "offline");
    }

    // Skip checks while the tab is hidden; coming back to the tab triggers one right away.
    function tick() {
      if (!document.hidden) poll();
    }

    poll();
    const id = setInterval(tick, POLL_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
      controller.abort();
    };
  }, []);

  const { label, box, dot } = STATUS[status];

  return (
    <output
      className={cn(
        "type-h4 inline-flex h-7 items-center gap-2 rounded-full border px-3 text-current",
        box,
      )}
    >
      <span
        className={cn("inline-flex size-2 rounded-full", dot)}
        aria-hidden="true"
      />
      {label}
    </output>
  );
}
