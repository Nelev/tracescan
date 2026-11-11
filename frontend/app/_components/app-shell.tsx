"use client";

import {
  Activity,
  LayoutDashboard,
  List,
  type LucideIcon,
  Network,
  Radar,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, Suspense } from "react";
import { runPath, shortId } from "@/lib/runs";
import { cn } from "@/lib/utils";
import { NewRun } from "./new-run";
import { RunStreamProvider, useRunStatus } from "./run-stream";
import { ServerStatus } from "./server-status";

function NavLink({
  href,
  label,
  Icon,
  active,
  live = false,
}: {
  href: string;
  label: string;
  Icon: LucideIcon;
  active: boolean;
  live?: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      title={label}
      className={cn(
        "type-body relative flex h-10 items-center gap-3 px-2.5 text-muted-foreground transition-colors hover:bg-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active &&
          "bg-hover text-foreground before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:bg-foreground",
      )}
    >
      <span className="relative flex">
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        {live && (
          <span
            className="absolute -top-0.5 -right-0.5 size-2 bg-info motion-safe:animate-pulse"
            aria-hidden="true"
          />
        )}
      </span>
      <span className="hidden truncate lg:inline">{label}</span>
    </Link>
  );
}

/**
 * The left nav: the runs, the traces, and the run this window started, while there is one.
 * `pathname` marks the open page; null while it is not known yet (the prerendered shell).
 */
function Nav({ pathname }: { pathname: string | null }) {
  const run = useRunStatus();
  const current = run.runId === null ? null : runPath(run.runId);
  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      <NavLink
        href="/"
        label="Dashboard"
        Icon={LayoutDashboard}
        active={pathname === "/"}
      />
      <NavLink
        href="/runs"
        label="Runs"
        Icon={List}
        active={
          pathname === "/runs" ||
          (pathname?.startsWith("/runs/") === true && pathname !== current)
        }
      />
      {current && (
        <NavLink
          href={current}
          label={`${run.phase === "running" ? "Live run" : "Last run"} ${shortId(run.runId as string)}`}
          Icon={Activity}
          active={pathname === current}
          live={run.phase === "running"}
        />
      )}
      <NavLink
        href="/traces"
        label="Traces"
        Icon={Network}
        active={pathname?.startsWith("/traces") === true}
      />
    </nav>
  );
}

function CurrentNav() {
  return <Nav pathname={usePathname()} />;
}

/**
 * Every page's frame: a slim nav on the left, a header with the backend's status and the New run
 * button, and the page. The run this window starts lives here, so it keeps streaming from page to
 * page.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <RunStreamProvider>
      <div className="flex min-h-full flex-1">
        <aside className="sticky top-0 flex h-screen w-14 shrink-0 flex-col gap-6 border-r bg-background px-2 py-3 lg:w-52 lg:px-3">
          <Link
            href="/"
            className="flex items-center gap-3 rounded-md px-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Radar className="size-4" aria-hidden="true" />
            </span>
            <span className="type-h3 hidden lg:inline">TraceScan</span>
          </Link>
          {/* The open page is known only per request: the shell is prerendered without it. */}
          <Suspense fallback={<Nav pathname={null} />}>
            <CurrentNav />
          </Suspense>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 flex h-14 items-center justify-end gap-3 border-b bg-background px-4 sm:px-6">
            <ServerStatus />
            <NewRun />
          </header>
          <main className="mx-auto flex w-full max-w-[96rem] flex-1 flex-col px-4 py-6 sm:px-6">
            {children}
          </main>
        </div>
      </div>
    </RunStreamProvider>
  );
}
