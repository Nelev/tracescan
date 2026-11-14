import { Suspense } from "react";
import { TracesList } from "@/app/_components/traces-list";

async function Traces({ searchParams }: PageProps<"/traces">) {
  // `?failed=1` opens the list filtered, so a filtered list survives a reload and can be shared.
  const { failed } = await searchParams;
  return <TracesList initialFailedOnly={failed === "1"} />;
}

export default function TracesPage(props: PageProps<"/traces">) {
  return (
    <Suspense
      fallback={
        <p className="type-body text-muted-foreground">Loading traces…</p>
      }
    >
      <Traces {...props} />
    </Suspense>
  );
}
