import { Suspense } from "react";
import { BadId } from "@/app/_components/bad-id";
import { RunView } from "@/app/_components/run-view";
import { decodeSegment } from "@/lib/format";
import { isRunId } from "@/lib/runs";

async function Run({ params, searchParams }: PageProps<"/runs/[id]">) {
  const id = decodeSegment((await params).id);
  if (!isRunId(id)) return <BadId id={id} kind="run" />;
  const { cluster } = await searchParams;
  return (
    <RunView
      key={id}
      runId={id}
      focusCluster={typeof cluster === "string" ? cluster : null}
    />
  );
}

export default function RunRoute(props: PageProps<"/runs/[id]">) {
  return (
    <Suspense
      fallback={<p className="type-body text-muted-foreground">Loading run…</p>}
    >
      <Run {...props} />
    </Suspense>
  );
}
