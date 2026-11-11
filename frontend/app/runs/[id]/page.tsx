import { Suspense } from "react";
import { RunView } from "../../_components/run-view";

async function Run({ params }: PageProps<"/runs/[id]">) {
  const { id } = await params;
  return <RunView key={id} runId={id} />;
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
