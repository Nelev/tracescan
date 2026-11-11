import { Radar } from "lucide-react";
import { RunPanel } from "./_components/run-panel";
import { ServerStatus } from "./_components/server-status";

export default function Home() {
  return (
    <>
      <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-background/70 px-4 backdrop-blur sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-[0_0_24px_-4px] shadow-primary">
            <Radar className="size-4" aria-hidden="true" />
          </div>
          <span className="type-h3">TraceScan</span>
        </div>
        <ServerStatus />
      </header>
      <main className="mx-auto flex w-full max-w-[96rem] flex-1 flex-col px-4 py-8 sm:px-6">
        <div className="mb-6 grid lg:grid-cols-12">
          <div className="flex flex-col gap-1 lg:col-span-9">
            <h1>Triage console</h1>
            <p className="type-body text-muted-foreground">
              Starts a triage run and shows the messages the server streams:
              drawn under Console, and as received under Raw events. Runs lists
              the runs the server has recorded, Run shows what one run found,
              cluster by cluster, Traces shows the stored traces span by span,
              and Review is where you approve or reject a run's proposals.
            </p>
          </div>
        </div>
        <RunPanel />
      </main>
    </>
  );
}
