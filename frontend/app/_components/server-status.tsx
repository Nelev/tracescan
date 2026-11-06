"use client";

import { useEffect, useState } from "react";
import { checkHealth } from "@/lib/api";
import { cn } from "@/lib/utils";

type Status = "checking" | "online" | "offline";

const POLL_MS = 15_000;

const STATUS: Record<Status, { label: string; box: string; dot: string }> = {
  checking: {
    label: "Checking backend…",
    box: "bg-muted text-muted-foreground",
    dot: "animate-pulse bg-muted-foreground",
  },
  online: {
    label: "Backend online",
    box: "border-success/30 bg-success/10 text-success",
    dot: "bg-success",
  },
  offline: {
    label: "Backend offline",
    box: "border-destructive/40 bg-destructive/10 text-destructive",
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
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-xs",
        box,
      )}
    >
      <span className="relative flex size-2">
        {status === "online" && (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
        )}
        <span className={cn("relative inline-flex size-2 rounded-full", dot)} />
      </span>
      {label}
    </output>
  );
}
