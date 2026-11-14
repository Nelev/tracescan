import { Suspense } from "react";
import { BadId } from "@/app/_components/bad-id";
import { TracePage } from "@/app/_components/trace-page";
import { decodeSegment } from "@/lib/format";
import { isTraceId } from "@/lib/traces";

async function Trace({ params, searchParams }: PageProps<"/traces/[id]">) {
  const id = decodeSegment((await params).id);
  if (!isTraceId(id)) return <BadId id={id} kind="trace" />;
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
