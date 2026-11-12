import { Suspense } from "react";
import { TracePage } from "@/app/_components/trace-page";

async function Trace({ params, searchParams }: PageProps<"/traces/[id]">) {
  const { id } = await params;
  const { span } = await searchParams;
  return (
    <TracePage
      key={id}
      traceId={id}
      spanId={typeof span === "string" ? span : null}
    />
  );
}

export default function TraceRoute(props: PageProps<"/traces/[id]">) {
  return (
    <Suspense
      fallback={
        <p className="type-body text-muted-foreground">Loading trace…</p>
      }
    >
      <Trace {...props} />
    </Suspense>
  );
}
