import { Suspense } from "react";
import { RunView } from "../../_components/run-view";

async function Run({ params, searchParams }: PageProps<"/runs/[id]">) {
  const { id } = await params;
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
